from django.apps import AppConfig


class BadmsConfig(AppConfig):
    name = "modules.badms"
    label = "badms"

    def ready(self) -> None:
        pass
