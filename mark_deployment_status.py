import argparse
import Backports
import config
import constants
import datetime
import json
import logging
import random
import re
import requests
import sys
import time
from pathlib import Path
from pwiki.wiki import Wiki  # type: ignore
from requests.adapters import HTTPAdapter
from urllib3 import Retry

args = argparse.Namespace(dry=False, verbose=False)
log = logging.getLogger("mark_deployment_status")
formatter = logging.Formatter("[%(asctime)s] [%(name)s] [%(levelname)s]: %(message)s")
log.addHandler(logging.StreamHandler(sys.stdout))
log.handlers[0].setFormatter(formatter)
sal_day_regex = re.compile(
    r"<a class=\"day\" href=\"/production\?d=(?P<day>\d{4}-\d{2}-\d{2})\">",
    re.IGNORECASE,
)

# Log in to the wiki
try:
    wiki = Wiki(
        constants.WIKITECH_WIKI,
        config.BOT_USERNAME,
        config.BOT_PASS,
        cookie_jar=Path(config.COOKIE_JAR),
    )
    wiki.save_cookies()
except Exception as e:
    log.error(e)
    exit(1)
re_get_deployments = re.compile(r"{{deploy\|.*?}}", re.IGNORECASE)


def get_request_session(
    extra_headers: dict[str, str] | None = None
) -> requests.Session:
    """Get a requests session object with the correct headers and settings"""
    headers = {
        "User-Agent": config.USER_AGENT,
    }
    if extra_headers:
        headers.update(extra_headers)

    s = requests.Session()
    s.headers.update(headers)
    # Retry 3 times with a backoff factor of 0.5 seconds
    retry = Retry(connect=3, backoff_factor=0.5)
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


def get_change_details(change_id: str):
    """Get the details of a Gerrit change"""
    session = get_request_session(
        {
            "Accept": "application/json",
        }
    )
    resp = session.get(
        f"https://{constants.GERRIT_URL}/r/changes/{change_id}",
        timeout=6,
    )
    if resp.status_code != 200:
        return None
    data = resp.content[4:]
    return json.loads(data)


def get_change_status(change_id: str) -> None | str:
    """Get the status of a Gerrit change"""
    change_details = get_change_details(change_id)
    if change_details:
        return change_details["status"]
    return None


def get_change_title(change_id: str) -> None | str:
    """Get the title of a Gerrit change"""
    change_details = get_change_details(change_id)
    if change_details:
        return change_details["subject"]
    return None


def get_sal_entry_day(sal_content: str) -> str:
    """Get the date of the SAL entry"""
    sal_day = sal_day_regex.search(sal_content)
    if sal_day is not None:
        return sal_day.group("day")
    return ""


def get_sal_entry_regex(title: str, gerrit_id: str) -> re.Pattern:
    """Return a prepared regex to find a SAL entry"""
    return re.compile(
        rf"<td class=\"time\"><a href=\"(?P<sal_link>.*?)\">(?P<deployed_at>\d\d:\d\d)<\/a><\/td>\s+<td class=\"nick\">&lt;(?P<deployer>.*?)@\w+&gt;<\/td>\s+<td class=\"message\">Finished scap sync-world: Backport for \[\[<a.*?>gerrit:{gerrit_id}.*?\|(?P<title>.*?)(\]\]|\()",  # noqa: E702
        re.IGNORECASE | re.DOTALL | re.MULTILINE,
    )


def did_change_get_deployed(
    gerrit_id: str, title: str, get_day: bool = False
) -> bool | re.Match[str] | tuple[re.Match[str], str]:
    """Find out if a change was deployed by checking the SAL on toolforge"""
    session = get_request_session()
    sal_content = session.get(
        f"https://{constants.SAL_URL}/production?p=0&q={gerrit_id}&d=",
        timeout=6,
    ).text
    in_log = get_sal_entry_regex(title, gerrit_id).search(sal_content)
    if in_log is not None:
        if get_day:
            sal_day = get_sal_entry_day(sal_content)
            if sal_day:
                return in_log, sal_day
        return in_log
    return False


def map_deployment_status(actual_status: str) -> None | str:
    """Map Gerrit statuses to deployment statuses"""
    new_status = None
    # TODO: Make this a switch statement
    if actual_status == "NEW":
        new_status = ""
    elif actual_status == "MERGED":
        new_status = "done"
    return new_status


def get_quirky_message() -> str | bool:
    """Get a quirky message"""
    try:
        with open("quirky.json", "r") as f:
            data = json.load(f)
        if len(data) == 0:
            log.error("quirky.json is empty")
            return False
        message = random.choice(data)
        return message
    except json.JSONDecodeError:
        log.error("quirky.json is not valid JSON")
        return False
    except FileNotFoundError:
        log.error("quirky.json not found")
        return False


def update_deployment_status(
    page_content: str,
    deployment: str,
    actual_status: str,
    reported_status: str,
    update: bool = False,
) -> bool | str:
    """Update the status of a deployment"""
    new_status = map_deployment_status(actual_status)
    deployment_obj = Backports.Deployment(deployment)
    if new_status is None:
        if args.verbose:
            log.info("Couldn't map status, not updating.")
        return False
    elif new_status == reported_status and not update:
        if args.verbose:
            log.info("Status is the same, not updating.")
        return False
    elif new_status == "done":
        gerrit_id = deployment_obj.gerrit_id
        deployment_title = deployment_obj.title
        if gerrit_id is None:
            if args.verbose:
                log.info("Couldn't get Gerrit ID, not updating.")
            return False
        if deployment_title is None:
            if args.verbose:
                log.info(f"[{gerrit_id}]: Couldn't get deployment title, not updating.")
            return False
        was_deployed = did_change_get_deployed(gerrit_id, deployment_title)
        if not was_deployed:
            # If the status was DONE (set by a person, probably), but we can't find it in the SAL
            # then we can't trust that it was actually done.

            # TODO: Remove this or put it behind a feature flag
            # log.info(
            #    f"[{gerrit_id}]: Cannot find this deployment in the SAL, marking as unknown status."
            # )
            # updated_deployment = re.sub(
            #    r"status=.*?(\||}})", "status=unknown\\1", deployment
            # )
            log.info(
                f'[{gerrit_id}]: Cannot find this deployment in the SAL, but trusting that it was "done".'
            )
            updated_deployment = deployment
            return updated_deployment
        else:
            # Quick guard against this returning a tuple now that its been updated
            if isinstance(was_deployed, tuple):
                was_deployed = was_deployed[0]
            updated_deployment = re.sub(
                r"status=.*?(\||}})", "status=done\\1", deployment
            )
            # If was_deployed is a regex match, we have some data
            if (
                isinstance(was_deployed, re.Match)
                and was_deployed.group("deployer") is not None
                and was_deployed.group("deployed_at") is not None
                and was_deployed.group("sal_link") is not None
            ):
                deployment_deployer = was_deployed.group("deployer")
                log.debug(f"[{gerrit_id}]: Found deployer: {deployment_deployer}")

                # Unused atm
                deployment_time = was_deployed.group("deployed_at")  # noqa: F841
                deployment_sal_link = (
                    f"https://{constants.SAL_URL}" + was_deployed.group("sal_link")
                )
                updated_deployment = re.sub(
                    r"status=done",
                    f"status=done|by={deployment_deployer}|sal={deployment_sal_link}",
                    updated_deployment,
                )
            else:
                log.error(f"[{gerrit_id}]: Missing deployer/deployed_at/sal_link")
            return updated_deployment
    else:
        log.error("Something went wrong..")
        return False


def normalise_deployment_status(deployment: str) -> str:
    """Normalise deployment status"""
    deployment = re.sub(r"status=d(\||}})", "status=done\\1", deployment)
    deployment = re.sub(r"status=nd(\||}})", "status=not done\\1", deployment)
    deployment = re.sub(r"status=m(\||}})", "status=unknown\\1", deployment)
    return deployment


def handle_reported_status(
    reported_status: str,
    deployment: str,
    actual_status: str,
    gerrit_id: str,
    page_content: str,
    deployments_to_update: dict[str, str],
    count: int,
) -> tuple[dict[str, str], int]:
    if reported_status == "":
        count += 1
        log.info(f"[{gerrit_id}]: Reported status is EMPTY, updating...")
        updated_deployment = update_deployment_status(
            page_content, deployment, actual_status, reported_status
        )
        if isinstance(updated_deployment, str):
            if updated_deployment != deployment:
                deployments_to_update[deployment] = updated_deployment
            else:
                log.debug(f"[{gerrit_id}]: No changes needed.")
    elif reported_status == "done":
        log.info(
            f"[{gerrit_id}]: Reported status is DONE — checking if it needs updating..."
        )
        # check if the sal link is present in the template
        if "sal=" not in deployment or "by=" not in deployment:
            log.debug(f"[{gerrit_id}]: Some parameters are missing, updating...")
            updated_deployment = update_deployment_status(
                page_content,
                deployment,
                actual_status,
                reported_status,
                update=True,
            )
            if isinstance(updated_deployment, str):
                if updated_deployment != deployment:
                    count += 1
                    deployments_to_update[deployment] = updated_deployment
                else:
                    log.debug(f"[{gerrit_id}]: No changes needed.")
    elif reported_status == "unknown":
        count += 1
        log.info(
            f"[{gerrit_id}]: Reported status is UNKNOWN — checking if it needs updating..."
        )
        updated_deployment = update_deployment_status(
            page_content, deployment, actual_status, reported_status
        )
        if isinstance(updated_deployment, str):
            if updated_deployment != deployment:
                deployments_to_update[deployment] = updated_deployment
            else:
                log.debug(f"[{gerrit_id}]: No changes needed.")
    else:
        log.info(
            f"[{gerrit_id}]: Reported status is {reported_status.upper()} — checking if it needs normalising..."
        )
        normalised_deployment = normalise_deployment_status(deployment)
        if normalised_deployment != deployment:
            count += 1
            log.info(f"[{gerrit_id}]: Deployment status will be normalised.")
            # TODO: If it gets normalised, we should check if it needs updating
            log.info(
                f"[{gerrit_id}]: Now checking if it needs updating after normalisation..."
            )
            updated_deployment = update_deployment_status(
                page_content, normalised_deployment, actual_status, reported_status
            )
            if isinstance(updated_deployment, str):
                if updated_deployment != normalised_deployment:
                    deployments_to_update[deployment] = updated_deployment
                    log.info(
                        f"[{gerrit_id}]: Some changes needed — will normalise and update."
                    )
                else:
                    deployments_to_update[deployment] = normalised_deployment
                    log.info(f"[{gerrit_id}]: No changes needed — will just normalise.")
            else:
                deployments_to_update[deployment] = normalised_deployment
                log.info(f"[{gerrit_id}]: No changes needed — will just normalise.")
        else:
            log.info(f"[{gerrit_id}]: No normalisation needed.")
    return deployments_to_update, count


def copy_for_testing(copy_from, copy_to) -> bool:
    """Copy the content of a page to another page for testing purposes"""
    # Check if the page exists
    if wiki.exists(copy_from) is False:
        log.error(f"Page {copy_from} does not exist")
        return False
    # Ask the user if they want to continue
    user_input = input(
        f"Are you sure you want to copy the content of {copy_from} to {copy_to}? (y/n) "
    )
    if user_input.lower() != "y":
        log.info("Aborting...")
        sys.exit(1)
    # Get the content of the page
    page_content = wiki.page_text(copy_from)
    # Remove the category
    page_content = page_content.replace("[[Category:Deployment]]", "")
    if args.dry is False and page_content:
        edit_result = wiki.edit(
            title=copy_to,
            text=page_content,
            summary=f"Copying content of {copy_from} for testing",
        )
        return edit_result
    else:
        log.info("Either dry run, or page content is empty.")
        return False


def log_to_wiki(message: str) -> None:
    """Log a message to the wiki"""
    log_page = (
        f"User:{config.BOT_USERNAME}/mark-deployment-status/{config.DEPLOYMENT_PAGE}"
    )
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if args.log_to_wiki:
        log.info(f"Logging message to {log_page}")
        log.debug(f"Message: * [{timestamp}]: {message}")
        if args.dry is False:
            wiki.edit(
                title=log_page,
                append=f"\n* [{timestamp}]: {message}",
                summary="Logging message",
                minor=True,
            )


def check_deployments(page_content: str) -> None:
    """Check deployments and update status if needed"""
    all_deployments = re_get_deployments.findall(page_content)
    log.info(
        f"Found {len(all_deployments)} total deployments on {config.DEPLOYMENT_PAGE}"
    )
    if args.log_to_wiki:
        log_to_wiki(
            f"Found {len(all_deployments)} total deployments on [[{config.DEPLOYMENT_PAGE}]]"
        )
    if len(all_deployments) == 0:
        log.info("No deployments found, exiting...")
        return
    deployments_to_update: dict[str, str] = {}
    seen_gerrit_ids = []
    limit = args.limit
    count = 0
    # We start from the most recent deployments, hence the `reversed`
    for deployment in reversed(all_deployments):
        if count >= limit:
            break
        # Slow down the requests to avoid hitting the API too hard
        time.sleep(0.2 + random.uniform(0, 0.5))
        # Parse deployment
        deployment_obj = Backports.Deployment(deployment)
        gerrit_id = deployment_obj.gerrit_id
        reported_status = deployment_obj.status
        deployment_title = deployment_obj.title
        deployment_type = deployment_obj.type

        if (
            gerrit_id is None
            or reported_status is None
            or deployment_title is None
            or deployment_type is None
        ):
            log.info(
                "Missing gerrit id/reported status/deployment title/deployment type"
            )
            continue

        if args.id and int(gerrit_id) != args.id:
            continue

        # Check if we've already seen this Gerrit ID
        if gerrit_id in seen_gerrit_ids:
            log.error(f"[{gerrit_id}]: Duplicate Gerrit ID found?!")
            if args.ignore_duplicates:
                log.info(f"[{gerrit_id}]: Ignoring duplicate Gerrit ID")
                continue
            # TODO: Handle this maybe?
            pass
        seen_gerrit_ids.append(gerrit_id)

        try:
            # get actual status
            actual_status = get_change_status(gerrit_id)
        except Exception as e:
            log.error(f"[{gerrit_id}]: Error getting actual status: {e}")
            sys.exit(1)

        if actual_status is None:
            log.info(f"[{gerrit_id}]: Could not get actual status for {gerrit_id}")
            continue

        log.info(
            f"[{gerrit_id}]: Checking status for {gerrit_id}: {deployment_title} ({deployment_type})"
        )
        log.info(
            f"[{gerrit_id}]: Actual status (according to Gerrit) is {actual_status}"
        )
        if reported_status == "" and actual_status == "NEW":
            log.debug(
                f"[{gerrit_id}]: Reported status is empty and actual status is new, no need to update."
            )
            continue

        # TODO: `count` here could just be `len(deployments_to_update)`, right..?
        deployments_to_update, count = handle_reported_status(
            reported_status,
            deployment,
            actual_status,
            gerrit_id,
            page_content,
            deployments_to_update,
            count,
        )
        if args.verbose:
            log.debug(
                f"len(deployments_to_update): {len(deployments_to_update)} ({count})"
            )
        print()
    print()
    if len(deployments_to_update) > 0:
        log.info(f"Found {len(deployments_to_update)} deployments to update")
        if args.log_to_wiki:
            log_message = f"Out of {len(all_deployments)} total deployments on [[{config.DEPLOYMENT_PAGE}]], there are {len(deployments_to_update)} deployments (limited to {args.limit} changes) to update"
            if args.id:
                log_message += f" (will only modify item with change ID: [[gerrit:{args.id}|{args.id}]])"
            log_to_wiki(log_message)
        new_page_content = page_content
        edit_summary = f"{config.EDIT_SUMMARY} [t:{len(all_deployments)}/u:{len(deployments_to_update)}/l:{args.limit}]"
        if args.id:
            edit_summary += f" (change ID: [[gerrit:{args.id}|{args.id}]])"
        if args.verbose:
            log.info(f"Edit summary: {edit_summary}")
        for deployment in deployments_to_update:
            if args.verbose:
                log.info(
                    f"Deployment {deployment} will be updated to {deployments_to_update[deployment]}"
                )
            new_page_content = new_page_content.replace(
                deployment, deployments_to_update[deployment]
            )
        if args.dry is False and new_page_content != page_content:
            log.info("Updating page...")
            edit_result = wiki.edit(
                title=config.DEPLOYMENT_PAGE,
                text=new_page_content,
                summary=edit_summary,
                minor=True,
            )
            if edit_result:
                log.info("Page updated successfully")
                if args.log_to_wiki:
                    log_message = f'<span style="color:green;">Successfully</span> updated {len(deployments_to_update)} deployments (limited to {args.limit} changes) on [[{config.DEPLOYMENT_PAGE}]]'  # noqa: E702
                    if args.id:
                        log_message += f" (will only modify item with change ID: [[gerrit:{args.id}|{args.id}]])"
                    log_to_wiki(log_message)
            else:
                log.error("Failed to update page")
                if args.log_to_wiki:
                    log_message = f'<span style="color:red;">Failed</span> to update {len(deployments_to_update)} deployments (limited to {args.limit} changes) on [[{config.DEPLOYMENT_PAGE}]]'  # noqa: E702
                    if args.id:
                        log_message += f" (will only modify item with change ID: [[gerrit:{args.id}|{args.id}]])"
                    log_to_wiki(log_message)
        if args.debug:
            with open("logs/deployments.txt", "w") as f:
                f.write(page_content)
            with open("logs/deployments_updated.txt", "w") as f:
                f.write(new_page_content)


def main() -> None:
    log.info(f"Getting deployments from {config.DEPLOYMENT_PAGE}...")
    if args.log_to_wiki:
        log_message = f"'''Beginning''' run for [[{config.DEPLOYMENT_PAGE}]] (limited to {args.limit} changes)"
        if args.id:
            log_message += f" (will only modify item with change ID: [[gerrit:{args.id}|{args.id}]])"
        log_to_wiki(log_message)
    page_content = wiki.page_text(config.DEPLOYMENT_PAGE)
    check_deployments(page_content)
    if args.log_to_wiki:
        log_message = f"'''Run completed''' for [[{config.DEPLOYMENT_PAGE}]] (limited to {args.limit} changes)"
        log_to_wiki(log_message)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        prog="mark-deployment-status.py",
        description=constants.DESCRIPTION,
    )
    # bool args
    parser.add_argument("-d", "--dry", help="Don't make any edits", action="store_true")
    parser.add_argument("-v", "--verbose", help="Be verbose", action="store_true")
    parser.add_argument("--version", help="Version & source info", action="store_true")
    parser.add_argument(
        "--clear-cookies",
        help="Clear any saved cookies from the jar",
        action="store_true",
    )
    parser.add_argument(
        "--ignore-duplicates", help="Ignore duplicate Gerrit IDs", action="store_true"
    )
    parser.add_argument(
        "--debug", help="Set log level to DEBUG, write logs etc.", action="store_true"
    )
    parser.add_argument(
        "--log-to-wiki", help="Log runs to a subpage", action="store_true"
    )
    # input args
    parser.add_argument(
        "-l",
        "--limit",
        help="Limit the number of deployments to modify (default: 60)",
        type=int,
        default=60,
        metavar="60",
    )
    parser.add_argument(
        "--id",
        help="Just update the status of a single deployment (by gerrit id)",
        type=str,
        metavar="12345",
    )
    parser.add_argument(
        "--page",
        help=f"Use a different page for deployments (default: {config.DEPLOYMENT_PAGE})",
        type=str,
        default=config.DEPLOYMENT_PAGE,
    )
    parser.add_argument(
        "--get-change-status",
        help="Get the patchset status of a change by Gerrit ID and quit",
        type=str,
        metavar="12345",
    )
    parser.add_argument(
        "--get-deployment-status",
        help="Get the deployment status of a change by Gerrit ID and quit",
        type=str,
        metavar="12345",
    )
    # Hidden args
    # Copy the content of the DEPLOYMENT_PAGE to the page provided (for testing)
    parser.add_argument(
        "--copy-for-testing",
        help=argparse.SUPPRESS,
        type=str,
        metavar="PAGE",
    )
    # Quirky feature
    parser.add_argument("--quirky", help=argparse.SUPPRESS, action="store_true")
    args = parser.parse_args()

    # Logging levels
    if args.debug:
        log.setLevel(logging.DEBUG)
    else:
        log.setLevel(logging.INFO)

    if args.quirky:
        message = get_quirky_message()
        if message:
            print(message)
        else:
            print("Sorry, we're all out of quirky messages")
        sys.exit(0)
    if args.get_change_status:
        change_status = get_change_status(args.get_change_status)
        if change_status:
            print(f"Change status: {change_status}")
        else:
            print("Change not found")
        sys.exit(0)
    if args.get_deployment_status:
        print(
            f"Getting deployment status for [[gerrit:{args.get_deployment_status}]]..."
        )
        change_title = get_change_title(args.get_deployment_status)
        change_status = get_change_status(args.get_deployment_status)
        if change_title and change_status:
            print(f"Change title: {change_title}")
            print(f"Change status: {change_status}")
            deployment_status = did_change_get_deployed(
                args.get_deployment_status, change_title, get_day=True
            )
            if deployment_status:
                if isinstance(deployment_status, tuple):
                    deployment_match = deployment_status[0]
                    deployment_day = deployment_status[1]
                    print(
                        f"Change deployed on {deployment_day} by {deployment_match.group('deployer')} (https://{constants.SAL_URL}{deployment_match.group('sal_link')})"
                    )  # noqa: E501
                elif isinstance(deployment_status, re.Match):
                    print(
                        f"Change deployed by {deployment_status.group('deployer')} (https://{constants.SAL_URL}{deployment_status.group('sal_link')})"
                    )  # noqa: E501
                else:
                    print("Unknown deployment status")
                    sys.exit(1)
            else:
                print("Change not deployed")
        else:
            print("Change not found")
        sys.exit(0)
    if args.version:
        print(constants.VERSION_STRING)
        sys.exit(0)
    if args.clear_cookies:
        log.info("Clearing cookies...")
        wiki.clear_cookies()
        sys.exit(0)
    if args.dry:
        log.info("Running in dry mode, no edits will be made.")
    if args.copy_for_testing:
        log.info(
            f"Copying content of {config.DEPLOYMENT_PAGE} to {args.copy_for_testing}..."
        )
        copy_result = copy_for_testing(config.DEPLOYMENT_PAGE, args.copy_for_testing)
        if copy_result:
            log.info(
                f"Successfully copied the content of {config.DEPLOYMENT_PAGE} to {args.copy_for_testing}"
            )
        else:
            log.error(
                f"Failed to copy the content of {config.DEPLOYMENT_PAGE} to {args.copy_for_testing}"
            )
        sys.exit(0)
    if args.id:
        log.info(f"Checking deployment with Gerrit ID {args.id} only")
    if args.page != config.DEPLOYMENT_PAGE:
        config.DEPLOYMENT_PAGE = args.page
        log.debug(f"Using page {config.DEPLOYMENT_PAGE} for deployments")
    if args.log_to_wiki:
        log_page = f"User:{config.BOT_USERNAME}/mark-deployment-status/{config.DEPLOYMENT_PAGE}"
        log.info(f"Logging runs to {log_page}")
        log_page_exists = wiki.exists(log_page)
        if not log_page_exists:
            log.info("Creating log page...")
            wiki.edit(
                title=log_page,
                text="Log page for mark-deployment-status.py\n\n",
                summary="Creating log page",
            )
    log.debug(f"Limiting to updating {args.limit} deployments")
    main()
