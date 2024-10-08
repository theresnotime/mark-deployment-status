import argparse
import json
import re
import requests
from pwiki.wiki import Wiki

# get https://gerrit.wikimedia.org/r/changes/1069293
wiki = Wiki("wikitech.wikimedia.org")
re_get_deployments = re.compile(r"{{deploy\|.*?}}", re.IGNORECASE)
re_get_gerrit = re.compile(r"gerrit=(?P<gerrit_id>\d+)", re.IGNORECASE)
re_get_status = re.compile(r"status=(?P<status>.*?)(}}|\|)", re.IGNORECASE)
re_get_title = re.compile(r"title=(?P<title>.*?)(}}|\|)", re.IGNORECASE)
re_get_type = re.compile(r"type=(?P<type>.*?)(}}|\|)", re.IGNORECASE)


def get_change_status(change_id):
    """Get the status of a Gerrit change"""
    headers = {"Accept": "application/json"}
    resp = requests.get(
        f"https://gerrit.wikimedia.org/r/changes/{change_id}",
        headers=headers,
    )
    if resp.status_code != 200:
        return None
    data = resp.content[4:]
    json_data = json.loads(data)
    return json_data["status"]


def get_sal_entry_regex(title, page):
    if page == "wiki":
        return re.compile(
            rf"\* (?P<deployed_at>\d\d:\d\d) (?P<deployer>.*?)@.*?: Finished scap sync-world: .*?{title}",
            re.IGNORECASE,
        )
    else:
        return re.compile(
            rf"<td class=\"message\">Finished scap sync-world: Backport for.*?{title}",
            re.IGNORECASE,
        )


def did_change_get_deployed(gerrit_id, title):
    # https://wikitech.wikimedia.org/wiki/Server_Admin_Log
    sal_content = wiki.page_text("Server_Admin_Log")
    in_log = get_sal_entry_regex(title, "wiki").search(sal_content)
    if in_log is not None:
        return True
    else:
        # https://sal.toolforge.org/production?p=0&q=&d=
        sal_content = requests.get(
            f"https://sal.toolforge.org/production?p=0&q={title}&d="
        ).text
        in_log = get_sal_entry_regex(title, "sal").search(sal_content)
        return in_log is not None


def get_gerrit_id(deployment):
    return re_get_gerrit.search(deployment).group("gerrit_id")


def get_reported_status(deployment):
    return re_get_status.search(deployment).group("status")


def parse_deployment(deployment):
    gerrit_id = get_gerrit_id(deployment)
    reported_status = get_reported_status(deployment)
    deployment_title = re_get_title.search(deployment).group("title")
    deployment_type = re_get_type.search(deployment).group("type")
    return gerrit_id, reported_status, deployment_title, deployment_type


def map_deployment_status(actual_status):
    new_status = None
    # TODO: Make this a switch statement
    if actual_status == "NEW":
        print("Change is new, updating status to '' (empty, for new)")
        new_status = ""
    elif actual_status == "MERGED":
        print("Change is merged, updating status to 'merged'")
        new_status = "d"
    return new_status


def update_deployment_status(page_content, deployment, actual_status, reported_status):
    new_status = map_deployment_status(actual_status)
    if new_status is None:
        print("Couldn't map status, not updating.")
        return False
    elif new_status == reported_status:
        print("Status is the same, not updating.")
        return False
    elif new_status == "d":
        was_deployed = did_change_get_deployed(
            get_gerrit_id(deployment), re_get_title.search(deployment).group("title")
        )
        if not was_deployed:
            print(
                "Change was not deployed (or can't be found in the recent SAL), not updating."
            )
            return False
        else:
            updated_deployment = re.sub(
                r"status=.*?(\||}})", f"status={new_status}\\1", deployment
            )
            print(f"Updating deployment: {deployment}")
            print(f"Updated deployment: {updated_deployment}")


def check_deployments(page_content):
    all_deployments = re_get_deployments.findall(page_content)
    print(f"Found {len(all_deployments)} deployments")
    for deployment in all_deployments:
        # Parse deployment
        (
            gerrit_id,
            reported_status,
            deployment_title,
            deployment_type,
        ) = parse_deployment(deployment)

        if (
            gerrit_id is None
            or reported_status is None
            or deployment_title is None
            or deployment_type is None
        ):
            print("Missing gerrit id/reported status/deployment title/deployment type")
            print("----")
            continue

        # get actual status
        actual_status = get_change_status(gerrit_id)

        if actual_status is None:
            print(f"Could not get actual status for {gerrit_id}")
            print("----")
            continue

        print(
            f"Checking status for {gerrit_id}: {deployment_title} ({deployment_type})"
        )
        print(f"Actual status (according to Gerrit) is {actual_status}")
        if reported_status == "" and actual_status == "NEW":
            print(
                "Reported status is empty and actual status is new, no need to update."
            )
            print("----")
            continue

        if reported_status == "":
            print("Reported status is empty, updating...")
            update_deployment_status(
                page_content, deployment, actual_status, reported_status
            )

        else:
            print(f"Reported status is not empty ({reported_status}), won't update.")

        print("----")


page_content = wiki.page_text("Deployments")
check_deployments(page_content)
