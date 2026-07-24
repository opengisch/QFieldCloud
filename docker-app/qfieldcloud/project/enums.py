from django.contrib.gis.db import models
from django.utils.translation import gettext as _


class ProjectRoleOrigins(models.TextChoices):
    PROJECTOWNER = "project_owner", _("Project owner")
    ORGANIZATIONOWNER = "organization_owner", _("Organization owner")
    ORGANIZATIONADMIN = "organization_admin", _("Organization admin")
    COLLABORATOR = "collaborator", _("Collaborator")
    TEAMMEMBER = "team_member", _("Team member")
    PUBLIC = "public", _("Public")


class QgsLayerType(models.IntegerChoices):
    """Mirrors QGIS's own `Qgis.LayerType` enum (`Qgis::LayerType`)
    Source: `enum class LayerType` in `src/core/qgis.h` in the QGIS repo
    (https://github.com/qgis/QGIS/blob/master/src/core/qgis.h).
    """

    Vector = 0, _("Vector")
    Raster = 1, _("Raster")
    Plugin = 2, _("Plugin")
    Mesh = 3, _("Mesh")
    VectorTile = 4, _("VectorTile")
    Annotation = 5, _("Annotation")
    PointCloud = 6, _("PointCloud")
    Group = 7, _("Group")
    TiledScene = 8, _("TiledScene")


class QgsGeometryType(models.IntegerChoices):
    """Mirrors QGIS's own `Qgis.GeometryType` enum (`Qgis::GeometryType`).
    Source: `enum class GeometryType` in `src/core/qgis.h` in the
    QGIS repo (https://github.com/qgis/QGIS/blob/master/src/core/qgis.h).
    """

    Point = 0, _("Point")
    Line = 1, _("Line")
    Polygon = 2, _("Polygon")
    Unknown = 3, _("Unknown")
    Null = 4, _("Null")


class ErrorCode(models.TextChoices):
    """QFieldCloud's own error taxonomy for layer processing.
    Values are produced in `docker-qgis/qfc_worker/utils.py`.
    Keep this in sync with that file.
    """

    NO_ERROR = "no_error", _("No error")
    INVALID_LAYER = "invalid_layer", _("Invalid layer")
    LOCALIZED_DATAPROVIDER = (
        "localized_dataprovider",
        _("Localized data provider"),
    )
    INVALID_DATAPROVIDER = "invalid_dataprovider", _("Invalid data provider")
    MISSING_DATAPROVIDER = "missing_dataprovider", _("Missing data provider")
