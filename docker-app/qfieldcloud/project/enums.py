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


class QgsLayerErrorCode(models.TextChoices):
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


class QgsFieldConstraintStrength(models.TextChoices):
    """Close mirror to QGIS's own `ConstraintStrength` enum (`ConstraintStrength`).
    Source: `enum ConstraintStrength` in `src/core/qgsfieldconstraints.h` in the QGIS repo
    (https://github.com/qgis/QGIS/blob/master/src/core/qgsfieldconstraints.h#L63)

    Values are produced by `get_constraint_strength()` in
    `docker-qgis/qfc_worker/utils.py`. Keep this in sync with that function.
    """

    NOT_SET = "not_set", _("Not set")
    HARD = "hard", _("Hard")
    SOFT = "soft", _("Soft")


class QtType(models.IntegerChoices):
    """Mirrors Qt's own `QMetaType::Type` enum.
    Source: https://doc.qt.io/qt-6/qmetatype.html#Type-enum
    """

    UnknownType = 0, _("UnknownType")
    Bool = 1, _("Bool")
    Int = 2, _("Int")
    UInt = 3, _("UInt")
    LongLong = 4, _("LongLong")
    ULongLong = 5, _("ULongLong")
    Double = 6, _("Double")
    Long = 32, _("Long")
    Short = 33, _("Short")
    Char = 34, _("Char")
    ULong = 35, _("ULong")
    UShort = 36, _("UShort")
    UChar = 37, _("UChar")
    Float = 38, _("Float")
    VoidStar = 31, _("VoidStar")
    QChar = 7, _("QChar")
    QString = 10, _("QString")
    QStringList = 11, _("QStringList")
    QByteArray = 12, _("QByteArray")
    QBitArray = 13, _("QBitArray")
    QDate = 14, _("QDate")
    QTime = 15, _("QTime")
    QDateTime = 16, _("QDateTime")
    QUrl = 17, _("QUrl")
    QLocale = 18, _("QLocale")
    QRect = 19, _("QRect")
    QRectF = 20, _("QRectF")
    QSize = 21, _("QSize")
    QSizeF = 22, _("QSizeF")
    QLine = 23, _("QLine")
    QLineF = 24, _("QLineF")
    QPoint = 25, _("QPoint")
    QPointF = 26, _("QPointF")
    QEasingCurve = 29, _("QEasingCurve")
    QUuid = 30, _("QUuid")
    QVariant = 41, _("QVariant")
    QModelIndex = 42, _("QModelIndex")
    QPersistentModelIndex = 50, _("QPersistentModelIndex")
    QRegularExpression = 44, _("QRegularExpression")
    QJsonValue = 45, _("QJsonValue")
    QJsonObject = 46, _("QJsonObject")
    QJsonArray = 47, _("QJsonArray")
    QJsonDocument = 48, _("QJsonDocument")
    QByteArrayList = 49, _("QByteArrayList")
    QObjectStar = 39, _("QObjectStar")
    SChar = 40, _("SChar")
    Void = 43, _("Void")
    Nullptr = 51, _("Nullptr")
    QVariantMap = 8, _("QVariantMap")
    QVariantList = 9, _("QVariantList")
    QVariantHash = 28, _("QVariantHash")
    QVariantPair = 58, _("QVariantPair")
    QCborSimpleType = 52, _("QCborSimpleType")
    QCborValue = 53, _("QCborValue")
    QCborArray = 54, _("QCborArray")
    QCborMap = 55, _("QCborMap")
    Char16 = 56, _("Char16")
    Char32 = 57, _("Char32")
    Int128 = 59, _("Int128")
    UInt128 = 60, _("UInt128")
    Float128 = 61, _("Float128")
    BFloat16 = 62, _("BFloat16")
    Float16 = 63, _("Float16")

    # Gui types
    QFont = 0x1000, _("QFont")
    QPixmap = 0x1001, _("QPixmap")
    QBrush = 0x1002, _("QBrush")
    QColor = 0x1003, _("QColor")
    QPalette = 0x1004, _("QPalette")
    QIcon = 0x1005, _("QIcon")
    QImage = 0x1006, _("QImage")
    QPolygon = 0x1007, _("QPolygon")
    QRegion = 0x1008, _("QRegion")
    QBitmap = 0x1009, _("QBitmap")
    QCursor = 0x100A, _("QCursor")
    QKeySequence = 0x100B, _("QKeySequence")
    QPen = 0x100C, _("QPen")
    QTextLength = 0x100D, _("QTextLength")
    QTextFormat = 0x100E, _("QTextFormat")
    QTransform = 0x1010, _("QTransform")
    QMatrix4x4 = 0x1011, _("QMatrix4x4")
    QVector2D = 0x1012, _("QVector2D")
    QVector3D = 0x1013, _("QVector3D")
    QVector4D = 0x1014, _("QVector4D")
    QQuaternion = 0x1015, _("QQuaternion")
    QPolygonF = 0x1016, _("QPolygonF")
    QColorSpace = 0x1017, _("QColorSpace")

    # Widget types
    QSizePolicy = 0x2000, _("QSizePolicy")

    # Start-point for client-code types
    User = 65536, _("User")
