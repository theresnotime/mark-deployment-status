# mark-deployment-status
A bot task which:
- scans the deployment page on the Wikitech wiki for backport window items (iff they are using the correct template),
- sets their deployment status to either "done" or "not done",
- attempt to mark which deployer did the item's deployment (based on the SAL entry) and,
- link the deployment item to said SAL entry

## Config
### config.py
Copy `config.example.py` to `config.py` and fill out the details:
```python
BOT_USERNAME = "TNTBot"
BOT_PASS = ""
DEPLOYMENT_PAGE = "Deployments"
EDIT_SUMMARY = "[[User:TNTBot#Updating_backport_window_deployment_statuses|Automated task]]: Updating deployment statuses"
USER_AGENT = (
    "TNTBot (https://meta.wikimedia.org/wiki/User:TNTBot) - mark-deployment-status"
)
COOKIE_JAR = "./.cookie_store"
```
### constants.py
Some stuff is *also* defined in `constants.py`, but they probably don't need to be changed.
```python
DESCRIPTION = "Script to mark deployment statuses on wikitech"
SOURCE = "https://github.com/theresnotime/mark-deployment-status"
__version__ = "0.1.0"
VERSION_STRING = f"{DESCRIPTION}\nv{__version__} ({SOURCE})"
WIKITECH_WIKI = "wikitech.wikimedia.org"
GERRIT_URL = "gerrit.wikimedia.org"
SAL_URL = "sal.toolforge.org"
```

## TODOs
### Handle unknown state
```python
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
```

### Handle duplicate Gerrit IDs
```python
# Check if we've already seen this Gerrit ID
if gerrit_id in seen_gerrit_ids:
    log.error(f"[{gerrit_id}]: Duplicate Gerrit ID found?!")
    if args.ignore_duplicates:
        log.info(f"[{gerrit_id}]: Ignoring duplicate Gerrit ID")
        continue
    # TODO: Handle this maybe?
    pass
seen_gerrit_ids.append(gerrit_id)
```

### Remove unneeded `count` variable
```python
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
```