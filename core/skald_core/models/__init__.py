"""Model file installer, revision management, project pin checks, and license acceptance."""

from skald_core.models.installer import (
    LICENSES_FILENAME,
    RECENT_PROJECTS_FILENAME,
    accept_license,
    install_model,
    is_license_accepted,
    licenses_path,
    list_installed_models,
    remove_model,
    submit_model_install,
    submit_model_remove,
    submit_model_update,
    update_model,
)

__all__ = [
    "LICENSES_FILENAME",
    "RECENT_PROJECTS_FILENAME",
    "accept_license",
    "install_model",
    "is_license_accepted",
    "licenses_path",
    "list_installed_models",
    "remove_model",
    "submit_model_install",
    "submit_model_remove",
    "submit_model_update",
    "update_model",
]
