import re

re_get_gerrit = re.compile(r"gerrit=(?P<gerrit_id>\d+)", re.IGNORECASE)
re_get_status = re.compile(r"status=(?P<status>.*?)(}}|\|)", re.IGNORECASE)
re_get_title = re.compile(r"title=(?P<title>.*?)(}}|\|)", re.IGNORECASE)
re_get_type = re.compile(r"type=(?P<type>.*?)(}}|\|)", re.IGNORECASE)


class Deployment:
    def __init__(self, deployment: str):
        self.deployment = deployment
        (
            self.gerrit_id,
            self.status,
            self.title,
            self.type,
        ) = self.parse_deployment()

    def parse_deployment(self) -> tuple[str | None, str | None, str | None, str | None]:
        """Parse a deployment string"""
        gerrit_id = self.get_gerrit_id()
        reported_status = self.get_reported_status()
        deployment_title = self.get_deployment_title()
        deployment_type = self.get_deployment_type()
        return gerrit_id, reported_status, deployment_title, deployment_type

    def get_gerrit_id(self) -> None | str:
        """Extract the Gerrit ID from a deployment string"""
        match = re_get_gerrit.search(self.deployment)
        if match:
            return match.group("gerrit_id")
        else:
            return None

    def get_reported_status(self) -> None | str:
        """Extract the status from a deployment string"""
        match = re_get_status.search(self.deployment)
        if match:
            return match.group("status")
        else:
            return None

    def get_deployment_title(self) -> None | str:
        """Extract the title from a deployment string"""
        match = re_get_title.search(self.deployment)
        if match:
            return match.group("title")
        else:
            return None

    def get_deployment_type(self) -> None | str:
        """Extract the type from a deployment string"""
        match = re_get_type.search(self.deployment)
        if match:
            return match.group("type")
        else:
            return None
