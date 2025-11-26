import os
import re
import shutil
import unicodedata
from html.parser import HTMLParser
from io import StringIO
from pathlib import Path

from qgis.core import (
    Qgis,
    QgsAttributeEditorContainer,
    QgsAttributeEditorField,
    QgsAttributeEditorRelation,
    QgsAttributeEditorTextElement,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsCsException,
    QgsDefaultValue,
    QgsEditFormConfig,
    QgsEditorWidgetSetup,
    QgsExpression,
    QgsFeature,
    QgsFeatureRequest,
    QgsFeatureSink,
    QgsField,
    QgsFieldConstraints,
    QgsFields,
    QgsMapLayer,
    QgsMapSettings,
    QgsOptionalExpression,
    QgsProject,
    QgsProperty,
    QgsPropertyCollection,
    QgsRasterLayer,
    QgsRectangle,
    QgsRelation,
    QgsRelationContext,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsVectorLayerUtils,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QMetaType, QObject, QSize, pyqtSignal

MARKDOWN_AVAILABLE = True
try:
    import markdown
except ImportError:
    MARKDOWN_AVAILABLE = False


class HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.reset()
        self.strict = False
        self.convert_charrefs = True
        self.text = StringIO()

    def handle_data(self, d):
        self.text.write(d)

    def get_data(self):
        return self.text.getvalue()


def strip_tags(html):
    s = HTMLStripper()
    s.feed(html)
    return s.get_data()


class XLSFormConverter(QObject):
    xlsx_form_file = ""

    survey_layer = None
    choices_layer = None
    settings_layer = None

    output_field = None
    output_extent = None
    output_project = None

    custom_title = None
    preferred_language = None
    basemap = None
    crs = QgsCoordinateReferenceSystem("EPSG:3857")
    extent = QgsRectangle()
    geometries = None
    groups_as_tabs = False

    label_field_name = "label"

    survey_skip_first = False
    survey_type_index = -1
    survey_name_index = -1
    survey_label_index = -1
    survey_calculation_index = -1
    survey_relevant_index = -1
    survey_choice_filter_index = -1
    survey_parameters_index = -1
    survey_constraint_index = -1
    survey_constraint_message_index = -1
    survey_required_index = -1
    survey_default_index = -1
    survey_read_only_index = -1
    survey_trigger_index = -1

    choices_skip_first = False
    choices_list_name_index = -1
    choices_name_index = -1
    choices_label_index = -1

    settings_skip_first = False
    settings_form_title_index = -1
    settings_form_id_index = -1
    settings_default_language_index = -1

    calculate_expressions = {}

    multimedia_info_pushed = False
    barcode_info_pushed = False

    info = pyqtSignal(str)
    warning = pyqtSignal(str)
    error = pyqtSignal(str)

    FIELD_TYPES = [
        "integer",
        "decimal",
        "range",
        "date",
        "time",
        "datetime",
        "text",
        "barcode",
        "image",
        "audio",
        "background-audio",
        "video",
        "file",
        "select_one",
        "select_one_from_file",
        "select_multiple",
        "select_multiple_from_file",
        "acknowledge",
        "rank",
        "calculate",
        "hidden",
    ]
    METADATA_TYPES = [
        "start",
        "end",
        "today",
        "deviceid",
        "phonenumber",
        "username",
        "email",
        "audit",
    ]

    BASEMAPS = {
        "OpenStreetMap": "type=xyz&tilePixelRatio=1&url=https://tile.openstreetmap.org/%7Bz%7D/%7Bx%7D/%7By%7D.png&zmax=19&zmin=0&crs=EPSG3857",
        "HOT": "type=xyz&tilePixelRatio=1&url=https://a.tile.openstreetmap.fr/hot/%7Bz%7D/%7Bx%7D/%7By%7D.png&zmax=19&zmin=0&crs=EPSG3857",
    }

    def __init__(self, xlsx_form_file):
        QObject.__init__(self)
        if not os.path.isfile(xlsx_form_file):
            return

        self.xlsx_form_file = xlsx_form_file

        self.survey_layer = QgsVectorLayer(
            xlsx_form_file
            + "|layername=survey|option:FIELD_TYPES=STRING|option:HEADERS=FORCE",
            "survey",
            "ogr",
        )
        if self.survey_layer.isValid():
            fields = self.survey_layer.fields().names()
            if fields[0] == "Field1":
                self.survey_skip_first = True
                fields = self.survey_layer.getFeature(1).attributes()

            self.survey_type_index = fields.index("type") if "type" in fields else -1
            self.survey_name_index = fields.index("name") if "name" in fields else -1
            self.survey_label_index = fields.index("label") if "label" in fields else -1
            self.survey_calculation_index = (
                fields.index("calculation") if "calculation" in fields else -1
            )
            self.survey_relevant_index = (
                fields.index("relevant") if "relevant" in fields else -1
            )
            self.survey_choice_filter_index = (
                fields.index("choice_filter") if "choice_filter" in fields else -1
            )
            self.survey_parameters_index = (
                fields.index("parameters") if "parameters" in fields else -1
            )
            self.survey_constraint_index = (
                fields.index("constraint") if "constraint" in fields else -1
            )
            self.survey_constraint_message_index = (
                fields.index("constraint_message")
                if "constraint_message" in fields
                else -1
            )
            self.survey_required_index = (
                fields.index("required") if "required" in fields else -1
            )
            self.survey_default_index = (
                fields.index("default") if "default" in fields else -1
            )
            self.survey_read_only_index = (
                fields.index("read_only") if "read_only" in fields else -1
            )
            self.survey_trigger_index = (
                fields.index("trigger") if "trigger" in fields else -1
            )

        self.choices_layer = QgsVectorLayer(
            xlsx_form_file
            + "|layername=choices|option:FIELD_TYPES=STRING|option:HEADERS=FORCE",
            "options",
            "ogr",
        )
        if self.choices_layer.isValid():
            fields = self.choices_layer.fields().names()
            if fields[0] == "Field1":
                self.choices_skip_first = True
                fields = self.choices_layer.getFeature(1).attributes()

            self.choices_list_name_index = (
                fields.index("list_name") if "list_name" in fields else -1
            )
            if self.choices_list_name_index == -1:
                self.choices_list_name_index = (
                    fields.index("list name") if "list name" in fields else -1
                )
            self.choices_name_index = fields.index("name") if "name" in fields else -1
            self.choices_name_index = fields.index("label") if "label" in fields else -1

        self.settings_layer = QgsVectorLayer(
            xlsx_form_file
            + "|layername=settings|option:FIELD_TYPES=STRING|option:HEADERS=FORCE",
            "settings",
            "ogr",
        )
        if self.settings_layer.isValid():
            fields = self.settings_layer.fields().names()
            if fields[0] == "Field1":
                self.settings_skip_first = True
                fields = self.settings_layer.getFeature(1).attributes()

            self.settings_form_title_index = (
                fields.index("form_title") if "form_title" in fields else -1
            )
            self.settings_form_id_index = (
                fields.index("form_id") if "form_id" in fields else -1
            )
            self.settings_default_language_index = (
                fields.index("default_language") if "default_language" in fields else -1
            )

    def is_valid(self):
        # Missing the one layer that must be available
        if not self.survey_layer or not self.survey_layer.isValid():
            return False

        # Missing the two basic parameters that must be present within the survey layer
        if self.survey_type_index == -1 or self.survey_name_index == -1:
            return False

        return True

    def create_field(self, feature):
        if not feature.attribute(self.survey_type_index) or not feature.attribute(
            self.survey_name_index
        ):
            return None

        type_details = str(feature.attribute(self.survey_type_index)).split(" ")
        type_details[0] = type_details[0].lower()

        field_name = str(feature.attribute(self.survey_name_index)).strip()
        field_alias = (
            str(feature.attribute(self.survey_label_index)).strip()
            if feature.attribute(self.survey_label_index)
            else field_name
        )
        field_alias = strip_tags(field_alias)

        field_type = None
        field = None

        if type_details[0] == "integer":
            field_type = QMetaType.Type.LongLong
        elif type_details[0] == "decimal":
            field_type = QMetaType.Type.Double
        elif type_details[0] == "range":
            field_type = QMetaType.Type.Double
        elif type_details[0] == "date" or type_details[0] == "today":
            field_type = QMetaType.Type.QDate
        elif type_details[0] == "time":
            field_type = QMetaType.Type.QTime
        elif (
            type_details[0] == "datetime"
            or type_details[0] == "start"
            or type_details[0] == "end"
        ):
            field_type = QMetaType.Type.QDateTime
        elif type_details[0] == "acknowledge":
            field_type = QMetaType.Type.Bool
        elif (
            type_details[0] == "text"
            or type_details[0] == "barcode"
            or type_details[0] == "image"
            or type_details[0] == "audio"
            or type_details[0] == "background-audio"
            or type_details[0] == "video"
            or type_details[0] == "file"
            or type_details[0] == "select_one"
            or type_details[0] == "select_one_from_file"
            or type_details[0] == "select_multiple"
            or type_details[0] == "select_multiple_from_file"
            or type_details[0] == "username"
            or type_details[0] == "email"
        ):
            field_type = QMetaType.Type.QString

            if type_details[0] == "barcode":
                if not self.barcode_info_pushed:
                    self.info.emit(
                        self.tr(
                            "Barcode functionality is only available through QField; it will be a simple text field in QGIS"
                        )
                    )
                    self.barcode_info_pushed = True
            elif (
                type_details[0] == "image"
                or type_details[0] == "audio"
                or type_details[0] == "video"
                or type_details[0] == "background-audio"
            ):
                if type_details[0] == "background-audio":
                    self.warning.emit(
                        self.tr(
                            "Unsupported type background-audio, using audio instead"
                        )
                    )

                if not self.multimedia_info_pushed:
                    self.info.emit(
                        self.tr(
                            "Multimedia content can be captured using QField on devices with cameras and microphones; in QGIS, pre-existing files can be selected."
                        )
                    )
                    self.multimedia_info_pushed = True
            elif type_details[0] == "username" or type_details[0] == "email":
                self.info.emit(
                    self.tr(
                        "The metadata {} is only available through QFieldCloud; it will return an empty value in QGIS".format(
                            type_details[0]
                        )
                    )
                )
        elif type_details[0] == "calculate" or type_details[0] == "hidden":
            field_type = QMetaType.Type.QString

            if self.survey_calculation_index >= 0:
                field_calculation = (
                    str(feature.attribute(self.survey_calculation_index)).strip()
                    if feature.attribute(self.survey_calculation_index)
                    else ""
                )
                if field_calculation != "":
                    self.calculate_expressions[field_name] = field_calculation

        if field_type:
            field = QgsField(field_name, field_type)
            field.setAlias(field_alias)

            field_constraints = QgsFieldConstraints()

            if self.survey_constraint_index >= 0:
                field_constraint_expression = (
                    str(feature.attribute(self.survey_constraint_index)).strip()
                    if feature.attribute(self.survey_constraint_index)
                    else ""
                )
                if field_constraint_expression != "":
                    field_constraint_expression = self.convert_expression(
                        field_constraint_expression, dot_field_name=field_name
                    )

                    field_constraint_message = (
                        str(
                            feature.attribute(self.survey_constraint_message_index)
                        ).strip()
                        if self.survey_constraint_message_index >= 0
                        and feature.attribute(self.survey_constraint_message_index)
                        else ""
                    )

                    # setup constraints
                    field_constraints.setConstraintExpression(
                        field_constraint_expression, field_constraint_message
                    )
                    field_constraints.setConstraintStrength(
                        QgsFieldConstraints.ConstraintExpression,
                        QgsFieldConstraints.ConstraintStrengthHard,
                    )

            if self.survey_required_index >= 0:
                field_required = (
                    str(feature.attribute(self.survey_required_index)).strip().lower()
                    if feature.attribute(self.survey_required_index)
                    else ""
                )

                if field_required == "yes":
                    field_constraints.setConstraint(
                        QgsFieldConstraints.ConstraintNotNull,
                        QgsFieldConstraints.ConstraintOriginLayer,
                    )
                    field_constraints.setConstraintStrength(
                        QgsFieldConstraints.ConstraintNotNull,
                        QgsFieldConstraints.ConstraintStrengthHard,
                    )

            field.setConstraints(field_constraints)

        return field

    def create_layer(self, name=None):
        if name:
            self.info.emit(self.tr("Creating child survey layer {}".format(name)))
        else:
            self.info.emit(self.tr("Creating main survey layer"))

        layer_geometry = self.detect_geometry(name)
        layer_fields = self.detect_fields(name)

        writer_options = QgsVectorFileWriter.SaveVectorOptions()
        writer_options.actionOnExistingFile = (
            QgsVectorFileWriter.CreateOrOverwriteLayer
            if os.path.isfile(self.output_file)
            else QgsVectorFileWriter.CreateOrOverwriteFile
        )
        writer_options.layerName = "survey" if not name else name
        writer_options.fileEncoding = "utf-8"
        QgsVectorFileWriter.create(
            self.output_file,
            layer_fields,
            layer_geometry,
            QgsCoordinateReferenceSystem("EPSG:4326")
            if self.crs.authid() == "EPSG:3857"
            else self.crs,
            QgsProject.instance().transformContext(),
            writer_options,
        )

        layer = QgsVectorLayer(
            self.output_file + "|layername=" + writer_options.layerName,
            writer_options.layerName,
            "ogr",
        )
        if name:
            layer.setFlags(QgsMapLayer.Private)
        layer.setDefaultValueDefinition(
            layer.fields().indexOf("uuid"), QgsDefaultValue("uuid()", False)
        )

        for layer_field in layer_fields:
            field_index = layer.fields().indexOf(layer_field.name())
            if field_index >= 0:
                layer.setConstraintExpression(
                    field_index,
                    layer_field.constraints().constraintExpression(),
                    layer_field.constraints().constraintDescription(),
                )
                if (
                    layer_field.constraints().constraintStrength(
                        QgsFieldConstraints.ConstraintNotNull
                    )
                    == QgsFieldConstraints.ConstraintStrengthHard
                ):
                    layer.setFieldConstraint(
                        field_index,
                        QgsFieldConstraints.ConstraintNotNull,
                        QgsFieldConstraints.ConstraintStrengthHard,
                    )

        layer.setCustomProperty("QFieldSync/cloud_action", "offline")
        layer.setCustomProperty("QFieldSync/action", "offline")

        self.output_project.addMapLayer(layer)

        return layer

    def create_editor_widget(self, feature):
        type_details = str(feature.attribute(self.survey_type_index)).split(" ")
        type_details[0] = type_details[0].lower()

        editor_widget = None

        if type_details[0] == "integer" or type_details[0] == "decimal":
            editor_widget = QgsEditorWidgetSetup("Range", {})
            editor_widget = QgsEditorWidgetSetup("Range", {})
        elif type_details[0] == "range":
            if self.survey_parameters_index >= 0:
                parameters = str(feature.attribute(self.survey_parameters_index))

                start_value = re.search(
                    "start=\s*([0-9]+)", parameters, flags=re.IGNORECASE
                )
                start_value = start_value.group(1) if start_value else 0
                end_value = re.search(
                    "end=\s*([0-9]+)", parameters, flags=re.IGNORECASE
                )
                end_value = end_value.group(1) if end_value else 10
                step_value = re.search(
                    "step=\s*([0-9]+)", parameters, flags=re.IGNORECASE
                )
                step_value = step_value.group(1) if step_value else 1

                editor_widget = QgsEditorWidgetSetup(
                    "Range",
                    {
                        "Min": start_value,
                        "Max": end_value,
                        "Step": step_value,
                        "Style": "Slider",
                    },
                )
            else:
                editor_widget = QgsEditorWidgetSetup("Range", {})
        elif (
            type_details[0] == "date"
            or type_details[0] == "time"
            or type_details[0] == "datetime"
        ):
            field_format = "yyyy-MM-dd"
            if type_details[0] == "time":
                field_format = "HH:mm:ss"
            elif type_details[0] == "datetime":
                field_format = "yyyy-MM-dd HH:mm:ss"
            editor_widget = QgsEditorWidgetSetup(
                "DateTime",
                {
                    "field_format_overwrite": True,
                    "display_format": field_format,
                    "field_format": field_format,
                    "allow_null": True,
                    "calendar_popup": True,
                },
            )
        elif (
            type_details[0] == "image"
            or type_details[0] == "audio"
            or type_details[0] == "background-audio"
            or type_details[0] == "video"
            or type_details[0] == "file"
        ):
            document_viewer = 0
            if type_details[0] == "image":
                document_viewer = 1
            elif type_details[0] == "audio" or type_details[0] == "background-audio":
                document_viewer = 3
            elif type_details[0] == "video":
                document_viewer = 4
            editor_widget = QgsEditorWidgetSetup(
                "ExternalResource",
                {
                    "DocumentViewer": document_viewer,
                    "FileWidget": True,
                    "FileWidgetButton": True,
                    "RelativeStorage": 1,
                },
            )
        elif type_details[0] == "acknowledge":
            editor_widget = QgsEditorWidgetSetup("CheckBox", {})
        elif (
            type_details[0] == "text"
            or type_details[0] == "barcode"
            or type_details[0] == "calculate"
        ):
            editor_widget = QgsEditorWidgetSetup("TextEdit", {})
        elif (
            type_details[0] == "select_one"
            or type_details[0] == "select_multiple"
            or type_details[0] == "select_one_from_file"
            or type_details[0] == "select_multiple_from_file"
        ):
            list_key = "name"
            list_value = self.label_field_name
            if (
                type_details[0] == "select_one_from_file"
                or type_details[0] == "select_multiple_from_file"
            ):
                if len(type_details) >= 2:
                    list_name = "list_" + " ".join(type_details[1:])
                    if self.survey_parameters_index >= 0:
                        parameters = str(
                            feature.attribute(self.survey_parameters_index)
                        )
                        match = re.search("(?:value)\s*=\s*([^\s]*)", parameters)
                        if match:
                            list_key = match.group(1)
                        match = re.search("(?:label)\s*=\s*([^\s]*)", parameters)
                        if match:
                            list_value = match.group(1)
            else:
                list_name = "list_" + type_details[1]

            if list_name:
                value_layer = self.output_project.mapLayersByName(list_name)
                if value_layer:
                    allow_multi = (
                        type_details[0] == "select_multiple"
                        or type_details[0] == "select_multiple_from_file"
                    )
                    filter_expression = (
                        str(feature.attribute(self.survey_choice_filter_index)).strip()
                        if self.survey_choice_filter_index >= 0
                        and feature.attribute(self.survey_choice_filter_index)
                        else ""
                    )
                    if filter_expression != "":
                        filter_expression = self.convert_expression(
                            filter_expression, use_current_value=True
                        )
                    if (
                        type_details[0] == "select_multiple"
                        or type_details[0] == "select_multiple_from_file"
                    ):
                        if filter_expression != "":
                            filter_expression = (
                                '"'
                                + list_key
                                + "\" != '' and ("
                                + filter_expression
                                + ")"
                            )
                        else:
                            filter_expression = '"' + list_key + "\" != ''"
                    editor_widget = QgsEditorWidgetSetup(
                        "ValueRelation",
                        {
                            "Layer": value_layer[0].id(),
                            "LayerName": type_details[1],
                            "LayerProviderName": "ogr",
                            "LayerSource": value_layer[0].source(),
                            "Key": list_key,
                            "Value": list_value,
                            "AllowNull": False,
                            "AllowMulti": allow_multi,
                            "FilterExpression": filter_expression,
                        },
                    )
                else:
                    editor_widget = QgsEditorWidgetSetup("TextEdit", {})
            else:
                editor_widget = QgsEditorWidgetSetup("TextEdit", {})
        elif (
            type_details[0] == "today"
            or type_details[0] == "start"
            or type_details[0] == "end"
            or type_details[0] == "username"
            or type_details[0] == "email"
            or type_details[0] == "hidden"
        ):
            # Metadata values are hidden
            editor_widget = QgsEditorWidgetSetup("Hidden", {})

        if editor_widget and self.survey_calculation_index >= 0:
            calculation = (
                str(feature.attribute(self.survey_calculation_index)).strip()
                if feature.attribute(self.survey_calculation_index)
                else ""
            )
            field_alias = (
                str(feature.attribute(self.survey_label_index)).strip()
                if feature.attribute(self.survey_label_index)
                else ""
            )
            if calculation != "" and field_alias == "":
                editor_widget = QgsEditorWidgetSetup("Hidden", {})

        return editor_widget

    def detect_geometry(self, child_name=None):
        geometry = Qgis.WkbType.NoGeometry

        current_child_name = []
        it = self.survey_layer.getFeatures()
        if self.survey_skip_first:
            feature = QgsFeature()
            it.nextFeature(feature)

        for feature in it:
            feature_type = str(feature.attribute(self.survey_type_index)).strip()
            if feature_type == "begin repeat":
                current_child_name.append(feature.attribute(self.survey_name_index))
            elif feature_type == "end repeat":
                current_child_name.pop()
            else:
                if (
                    len(current_child_name) > 0 and current_child_name[-1] == child_name
                ) or (len(current_child_name) == 0 and not child_name):
                    type_details = str(feature.attribute(self.survey_type_index)).split(
                        " "
                    )[0]
                    if type_details == "geopoint" or type_details == "start-geopoint":
                        geometry = Qgis.WkbType.MultiPoint
                        break
                    if type_details == "geotrace" or type_details == "start-geotrace":
                        geometry = Qgis.WkbType.MultiLineString
                        break
                    if type_details == "geoshape" or type_details == "start-geoshape":
                        geometry = Qgis.WkbType.MultiPolygon
                        break

        return geometry

    def detect_fields(self, child_name=None):
        fields = QgsFields()

        fields.append(QgsField("uuid", QMetaType.Type.QString))
        if child_name:
            fields.append(QgsField("uuid_parent", QMetaType.Type.QString))

        current_child_name = []
        it = self.survey_layer.getFeatures()
        if self.survey_skip_first:
            feature = QgsFeature()
            it.nextFeature(feature)

        for feature in it:
            feature_type = str(feature.attribute(self.survey_type_index)).strip()
            feature_name = str(feature.attribute(self.survey_name_index)).strip()
            if feature_type == "begin repeat" or feature_type == "begin_repeat":
                current_child_name.append(feature_name)
            elif feature_type == "end repeat" or feature_type == "end_repeat":
                current_child_name.pop()
            else:
                if (
                    len(current_child_name) > 0 and current_child_name[-1] == child_name
                ) or (len(current_child_name) == 0 and not child_name):
                    field = self.create_field(feature)
                    if field:
                        fields.append(field)
                    else:
                        type_details = str(
                            feature.attribute(self.survey_type_index)
                        ).split(" ")
                        type_details[0] = type_details[0].lower()
                        if type_details[0] in self.FIELD_TYPES:
                            self.warning.emit(
                                self.tr(
                                    "Unsupported field type {} for layer {}, skipping".format(
                                        type_details[0],
                                        "survey" if not child_name else child_name,
                                    )
                                )
                            )
                        elif type_details[0] in self.METADATA_TYPES:
                            if (
                                not type_details[0] == "end"
                                or feature.attribute(self.survey_type_index)
                                .strip()
                                .lower()
                                == "end"
                            ):
                                self.warning.emit(
                                    self.tr(
                                        "Unsupported metadata {} for layer {}, skipping".format(
                                            type_details[0],
                                            "survey" if not child_name else child_name,
                                        )
                                    )
                                )

        return fields

    def convert_label_expression(self, original_label_expression):
        label_expression = original_label_expression

        # ${field} to "field"
        label_expression = label_expression.replace("'", "\\'")
        label_expression = re.sub(
            r"\$\{([^}]+)}", "' || \"\\1\" || '", label_expression
        )
        label_expression = "'{}'".format(label_expression)

        label_expression_try = QgsExpression(label_expression)
        if label_expression_try.hasParserError():
            self.warning.emit(
                self.tr(
                    "Unsupported label expression {}".format(original_label_expression)
                )
            )

        return label_expression

    def convert_choices(
        self, list_name, features, output_lists_field_names, output_lists_fields
    ):
        writer_options = QgsVectorFileWriter.SaveVectorOptions()
        writer_options.actionOnExistingFile = (
            QgsVectorFileWriter.CreateOrOverwriteLayer
            if os.path.isfile(self.output_file)
            else QgsVectorFileWriter.CreateOrOverwriteFile
        )
        writer_options.layerName = "list_" + list_name
        writer_options.fileEncoding = "utf-8"
        output_lists_sink = QgsVectorFileWriter.create(
            self.output_file,
            output_lists_fields,
            Qgis.WkbType.NoGeometry,
            QgsCoordinateReferenceSystem(4326),
            QgsProject.instance().transformContext(),
            writer_options,
        )

        # Add pseudo-NULL value
        output_feature = QgsFeature(output_lists_fields)
        output_feature.setAttribute("name", "")
        output_feature.setAttribute(self.label_field_name, "")
        output_lists_sink.addFeature(output_feature)

        for feature in features:
            output_feature = QgsFeature(output_lists_fields)
            for field_name in output_lists_field_names:
                attribute_value = feature.attribute(
                    output_lists_field_names.index(field_name)
                )
                if field_name == self.label_field_name:
                    attribute_value = strip_tags(str(attribute_value))
                output_feature.setAttribute(field_name, attribute_value)
            output_lists_sink.addFeature(output_feature)

        output_lists_sink.flushBuffer()
        del output_lists_sink
        output_lists_layer = QgsVectorLayer(
            self.output_file + "|layername=" + writer_options.layerName,
            writer_options.layerName,
            "ogr",
        )
        output_lists_layer.setFlags(QgsMapLayer.Private)
        output_lists_layer.setCustomProperty("QFieldSync/cloud_action", "no_action")
        output_lists_layer.setCustomProperty("QFieldSync/action", "copy")
        self.output_project.addMapLayer(output_lists_layer)

    def convert_external_choices(self, type_details):
        if len(type_details) < 2:
            return False

        from_file = " ".join(type_details[1:])
        from_file_path = Path(self.xlsx_form_file).parent.joinpath(from_file)
        if not from_file_path.exists():
            return False

        if self.output_project.mapLayersByName("list_" + from_file):
            return True

        output_from_file_path = Path(self.output_directory).joinpath(from_file)
        try:
            shutil.copy(str(from_file_path), str(output_from_file_path))
        except Exception:
            return False

        output_from_layer = QgsVectorLayer(
            str(output_from_file_path), "list_" + from_file, "ogr"
        )
        if not output_from_layer.isValid():
            del output_from_layer
            return False

        output_from_layer.setFlags(QgsMapLayer.Private)
        output_from_layer.setCustomProperty("QFieldSync/cloud_action", "no_action")
        output_from_layer.setCustomProperty("QFieldSync/action", "copy")
        self.output_project.addMapLayer(output_from_layer)
        return True

    def convert_expression(
        self,
        original_expression,
        use_current_value=False,
        use_insert=False,
        dot_field_name=None,
    ):
        expression = original_expression

        # be tolerant of ‘’ by replacing them with ''
        expression = expression.replace("‘", "'")
        expression = expression.replace("’", "'")

        # replace dot with field name
        if dot_field_name:
            expression = re.sub(
                r"(^|[\s<>=\(\)\,])\.($|[\s<>=\(\)\,])",
                r"\1${" + dot_field_name + r"}\2",
                expression,
            )

        # selected(${field}, value) to ${field} = value
        expression = re.sub(
            r"selected\s*\(\s*(\$\{[^}]+})\,([^)]+)\)", r"\1 = \2", expression
        )

        # regexp(${field}, value) to regexp_match(${field}, value)
        match = re.search(
            r"regex\s*\(\s*(\$\{[^}]+})\s*\,\s*'(.+)'\s*\)\s*$", expression
        )
        if match:
            # warning: ugly hack ahead
            expression = re.sub(
                r"regex\s*\(\s*(\$\{[^}]+})\s*\,\s*'(.+)'\s*\)\s*$",
                "regexp_match(\\1, '",
                expression,
            )
            expression = "{}{}')".format(
                expression, format(match.group(2).replace("\\", "\\\\"))
            )

            expression = re.sub(
                r"([^\[])\[:(digit|upper|lower|alpha|alnum|punct|blank|word):\]([^\]])",
                r"\1[[:\2:]]\3",
                expression,
            )

        if use_insert:
            if use_current_value:
                # ${field} = value to current_value('field')
                for (
                    calculate_name,
                    calculate_expression,
                ) in self.calculate_expressions.items():
                    expression = re.sub(
                        r"\$\{" + calculate_name + r"}",
                        r"[% "
                        + self.convert_expression(
                            calculate_expression, use_current_value=True
                        )
                        + r" %]",
                        expression,
                    )
                expression = re.sub(
                    r"\$\{([^}]+)}", r"[% current_value('\1') %]", expression
                )
            else:
                # ${field} = value to "field"
                for (
                    calculate_name,
                    calculate_expression,
                ) in self.calculate_expressions.items():
                    expression = re.sub(
                        r"\$\{" + calculate_name + r"}",
                        r"[% "
                        + self.convert_expression(
                            calculate_expression, use_current_value=False
                        )
                        + r" %]",
                        expression,
                    )
                expression = re.sub(r"\$\{([^}]+)}", r'[% "\1" %]', expression)
        else:
            if use_current_value:
                # ${field} = value to current_value('field')
                expression = re.sub(r"\$\{([^}]+)}", r"current_value('\1')", expression)
            else:
                # ${field} = value to "field"
                expression = re.sub(r"\$\{([^}]+)}", r'"\1"', expression)

        # today() to format_date(now()...)
        expression = re.sub(
            r"today\(\)", r"format_date(now(),'yyyy-MM-dd')", expression
        )

        # selected(1, 2) to 1 = 2
        expression = re.sub(
            r"selected\s*\(\s*(\$\{[^}]+})\,([^)]+)\)", r"\1 = \2", expression
        )

        if not use_insert:
            expression_try = QgsExpression(expression)
            if expression_try.hasParserError():
                self.warning.emit(
                    self.tr("Unsupported expression {}".format(original_expression))
                )

        return expression

    def process_project_write(self, document):
        nl = document.elementsByTagName("qgis")
        if nl.count() == 0:
            return

        qgisNode = nl.item(0)

        mapcanvasNode = document.createElement("mapcanvas")
        mapcanvasNode.setAttribute("name", "theMapCanvas")
        qgisNode.appendChild(mapcanvasNode)

        ms = QgsMapSettings()
        ms.setDestinationCrs(self.output_project.crs())
        ms.setOutputSize(QSize(500, 500))
        if self.output_extent:
            ms.setExtent(self.output_extent)
        ms.writeXml(mapcanvasNode, document)

    def set_custom_title(self, title: str) -> None:
        self.custom_title = title

    def set_preferred_language(self, language: str) -> None:
        self.preferred_language = language

    def set_basemap(self, basemap) -> None:
        self.basemap = basemap

    def set_crs(self, crs: QgsCoordinateReferenceSystem) -> None:
        if crs.isValid():
            self.crs = crs
        else:
            self.crs = QgsCoordinateReferenceSystem("EPSG:3857")

    def set_extent(self, extent):
        self.extent = extent

    def set_geometries(self, geometries):
        self.geometries = geometries

    def set_groups_as_tabs(self, groups_as_tabs):
        self.groups_as_tabs = groups_as_tabs

    def convert(
        self,
        output_directory,
    ):
        if not self.survey_layer:
            return ""

        os.makedirs(os.path.abspath(output_directory), exist_ok=True)
        self.output_directory = output_directory

        # Settings handling
        settings_title = "survey"
        settings_id = ""
        settings_language = ""

        # Project-wide image max-pixel parameter
        settings_max_pixels = 0

        if self.settings_layer.isValid():
            it = self.settings_layer.getFeatures()
            if self.settings_skip_first:
                feature = QgsFeature()
                it.nextFeature(feature)

            for feature in it:
                if self.settings_form_title_index >= 0 and feature.attribute(
                    self.settings_form_title_index
                ):
                    settings_title = feature.attribute(self.settings_form_title_index)
                if self.settings_form_id_index >= 0 and feature.attribute(
                    self.settings_form_id_index
                ):
                    settings_id = feature.attribute(self.settings_form_id_index)
                if self.settings_default_language_index >= 0 and feature.attribute(
                    self.settings_default_language_index
                ):
                    settings_language = feature.attribute(
                        self.settings_default_language_index
                    )
                break

        if self.custom_title:
            settings_title = self.custom_title

        if self.preferred_language:
            settings_language = self.preferred_language

        if settings_language != "":
            self.label_field_name = "label::{}".format(settings_language)
        else:
            self.label_field_name = "label"

        fields = self.survey_layer.fields().names()
        if fields[0] == "Field1":
            fields = self.survey_layer.getFeature(1).attributes()

        self.survey_label_index = -1
        for index, field in enumerate(fields):
            if field.lower() == self.label_field_name.lower():
                self.label_field_name = field
                self.survey_label_index = index
                break

        if self.survey_label_index == -1:
            fallback_label_field_name = ""
            fallback_survey_label_index = -1
            for index, field in enumerate(fields):
                if field.lower() == "label":
                    fallback_label_field_name = "label"
                    fallback_survey_label_index = index
                    break
                elif not fallback_label_field_name and field.lower().startswith(
                    "label::"
                ):
                    fallback_label_field_name = field
                    fallback_survey_label_index = index

            if fallback_survey_label_index >= 0:
                self.label_field_name = fallback_label_field_name
                self.survey_label_index = fallback_survey_label_index
                if settings_language:
                    self.info.emit(
                        self.tr(
                            "label::{} parameter not found in the survey layer, falling back to label".format(
                                settings_language
                            )
                        )
                    )
                else:
                    self.info.emit(
                        self.tr(
                            "Picked {} as language for the conversion".format(
                                self.label_field_name
                            )
                        )
                    )

        if self.survey_label_index == -1:
            self.error.emit(
                self.tr(
                    "{} parameter not found in the survey layer, aborting".format(
                        self.label_field_name
                    )
                )
            )
            return

        if self.choices_layer.isValid():
            fields = self.choices_layer.fields().names()
            if fields[0] == "Field1":
                fields = self.choices_layer.getFeature(1).attributes()

            self.choices_label_index = -1
            for index, field in enumerate(fields):
                if field.lower() == self.label_field_name.lower():
                    self.choices_label_index = index
                    break

            if self.choices_label_index == -1:
                self.error.emit(
                    self.tr(
                        "{} parameter not found in the choices layer, aborting".format(
                            self.label_field_name
                        )
                    )
                )
                return

        settings_filename = self.custom_title if self.custom_title else settings_title
        settings_filename = (
            unicodedata.normalize("NFKD", settings_filename)
            .encode("ascii", "ignore")
            .decode("ascii")
        )
        settings_filename = re.sub(r"[^\w\s-]", "", settings_filename)
        settings_filename = re.sub(r"[-\s]+", "-", settings_filename)

        self.info.emit(
            self.tr("Creating survey {} (id: {})".format(settings_title, settings_id))
        )

        # Project creationg
        self.output_file = str(
            os.path.join(output_directory, settings_filename + ".gpkg")
        )
        self.output_project = QgsProject()
        self.output_project.setCrs(self.crs)

        if self.basemap in self.BASEMAPS:
            base_layer = QgsRasterLayer(
                self.BASEMAPS[self.basemap],
                self.basemap,
                "wms",
            )
            self.output_project.addMapLayer(base_layer)

        # Choices handling
        output_lists_fields = QgsFields()
        output_lists_field_names = self.choices_layer.fields().names()
        if self.choices_skip_first:
            output_lists_field_names = self.choices_layer.getFeature(1).attributes()

        for field_name in output_lists_field_names:
            output_lists_fields.append(QgsField(field_name, QMetaType.Type.QString))

        lists = {}

        it = self.choices_layer.getFeatures()
        if self.choices_skip_first:
            feature = QgsFeature()
            it.nextFeature(feature)

        for feature in it:
            list_name = feature.attribute(self.choices_list_name_index)
            if not list_name:
                continue

            list_name = str(list_name)
            if list_name not in lists:
                lists[list_name] = []
            lists[list_name].append(feature)

        for list_name, features in lists.items():
            self.convert_choices(
                list_name, features, output_lists_field_names, output_lists_fields
            )

        # External choices handling
        it = self.survey_layer.getFeatures()
        if self.survey_skip_first:
            feature = QgsFeature()
            it.nextFeature(feature)

        for feature in it:
            feature_type = (
                str(feature.attribute(self.survey_type_index)).strip().lower()
            )
            type_details = feature_type.split(" ")
            if (
                type_details[0] == "select_multiple_from_file"
                or type_details[0] == "select_single_from_file"
            ):
                if not self.convert_external_choices(type_details):
                    self.warning.emit(
                        self.tr(
                            "Select from file could not be converted, {} turned into text field".format(
                                feature.attribute(self.survey_name_index)
                            )
                        )
                    )

        # Survey handling
        self.calculate_expressions = {}

        current_layer = [self.create_layer()]
        self.output_project.addMapLayer(current_layer[-1])

        current_editor_form = [current_layer[-1].editFormConfig()]
        current_editor_form[-1].invisibleRootContainer().clear()
        current_editor_form[-1].setLayout(Qgis.AttributeFormLayout.DragAndDrop)

        current_editor_group_level = [0]

        current_container = [
            QgsAttributeEditorContainer(
                "Survey", current_editor_form[-1].invisibleRootContainer()
            )
        ]
        current_container[-1].setType(Qgis.AttributeEditorContainerType.Tab)
        current_editor_form[-1].invisibleRootContainer().addChildElement(
            current_container[-1]
        )

        relation_context = QgsRelationContext(self.output_project)

        it = self.survey_layer.getFeatures()
        if self.survey_skip_first:
            feature = QgsFeature()
            it.nextFeature(feature)

        for feature in it:
            if not feature.attribute(self.survey_type_index):
                continue

            feature_type = (
                str(feature.attribute(self.survey_type_index)).strip().lower()
            )
            feature_name = str(feature.attribute(self.survey_name_index)).strip()
            feature_label = (
                str(feature.attribute(self.survey_label_index)).strip()
                if feature.attribute(self.survey_label_index)
                else ""
            )

            field_index = current_layer[-1].fields().indexOf(feature_name)

            relevant_container = None
            relevant_expression = (
                str(feature.attribute(self.survey_relevant_index)).strip()
                if self.survey_relevant_index >= 0
                and feature.attribute(self.survey_relevant_index)
                else ""
            )
            if relevant_expression != "":
                relevant_expression = self.convert_expression(relevant_expression)
                if field_index >= 0 or feature_type == "begin repeat":
                    relevant_container = QgsAttributeEditorContainer(
                        feature_name + " - relevant", current_container[-1]
                    )
                    relevant_container.setShowLabel(False)
                    relevant_container.setType(
                        Qgis.AttributeEditorContainerType.GroupBox
                    )
                    relevant_container.setVisibilityExpression(
                        QgsOptionalExpression(QgsExpression(relevant_expression))
                    )

            if feature_type == "begin repeat" or feature_type == "begin_repeat":
                current_layer.append(self.create_layer(feature_name))
                self.output_project.addMapLayer(current_layer[-1])

                current_editor_form.append(current_layer[-1].editFormConfig())
                current_editor_form[-1].invisibleRootContainer().clear()
                current_editor_form[-1].setLayout(Qgis.AttributeFormLayout.DragAndDrop)

                current_editor_group_level.append(0)

                current_container.append(
                    QgsAttributeEditorContainer(
                        "Survey", current_editor_form[-1].invisibleRootContainer()
                    )
                )
                current_container[-1].setType(Qgis.AttributeEditorContainerType.Tab)
                current_editor_form[-1].invisibleRootContainer().addChildElement(
                    current_container[-1]
                )

                relation = QgsRelation(relation_context)
                relation.setName(feature_name)
                relation.setReferencedLayer(current_layer[-2].id())
                relation.setReferencingLayer(current_layer[-1].id())
                relation.addFieldPair("uuid_parent", "uuid")
                relation.generateId()
                self.output_project.relationManager().addRelation(relation)

                editor_relation = QgsAttributeEditorRelation(
                    feature_name,
                    relation.id(),
                    current_editor_form[-2].invisibleRootContainer(),
                )
                feature_label = strip_tags(feature_label)
                editor_relation.setLabel(feature_label)
                editor_relation.setShowLabel(feature_label != "")
                if relevant_container:
                    relevant_container.addChildElement(editor_relation)
                    current_container[-2].addChildElement(relevant_container)
                else:
                    current_container[-2].addChildElement(editor_relation)
            elif feature_type == "end repeat" or feature_type == "end_repeat":
                if len(current_layer) > 1:
                    current_container.pop()
                    current_editor_group_level.pop()
                    current_layer[-1].setEditFormConfig(current_editor_form[-1])
                    current_layer.pop()
                    current_editor_form.pop()
            elif feature_type == "begin group" or feature_type == "begin_group":
                feature_label = strip_tags(feature_label)

                if self.groups_as_tabs and current_editor_group_level[-1] == 0:
                    current_container.append(
                        QgsAttributeEditorContainer(
                            feature_label,
                            current_editor_form[-1].invisibleRootContainer(),
                        )
                    )
                    current_container[-1].setType(Qgis.AttributeEditorContainerType.Tab)
                    if relevant_expression != "":
                        current_container[-1].setVisibilityExpression(
                            QgsOptionalExpression(QgsExpression(relevant_expression))
                        )
                    current_editor_form[-1].invisibleRootContainer().addChildElement(
                        current_container[-1]
                    )
                    current_editor_group_level[-1] = current_editor_group_level[-1] + 1
                else:
                    current_container.append(
                        QgsAttributeEditorContainer(
                            feature_label, current_container[-1]
                        )
                    )
                    current_container[-1].setType(
                        Qgis.AttributeEditorContainerType.GroupBox
                    )
                    current_container[-1].setShowLabel(feature_label != "")
                    if relevant_expression != "":
                        current_container[-1].setVisibilityExpression(
                            QgsOptionalExpression(QgsExpression(relevant_expression))
                        )
                    current_container[-2].addChildElement(current_container[-1])
                    current_editor_group_level[-1] = current_editor_group_level[-1] + 1
            elif feature_type == "end group" or feature_type == "end_group":
                if len(current_container) > 1:
                    current_container.pop()
                    current_editor_group_level[-1] = current_editor_group_level[-1] - 1
            elif feature_type == "note":
                editor_text = QgsAttributeEditorTextElement(
                    feature_name, current_container[-1]
                )

                if MARKDOWN_AVAILABLE:
                    feature_label = markdown.markdown(feature_label)

                editor_text.setText(
                    self.convert_expression(
                        feature_label, use_current_value=True, use_insert=True
                    )
                )
                editor_text.setShowLabel(False)
                current_container[-1].addChildElement(editor_text)
            elif field_index >= 0:
                editor_widget = None
                editor_element = None

                editor_widget = self.create_editor_widget(feature)
                if editor_widget:
                    current_layer[-1].setEditorWidgetSetup(field_index, editor_widget)
                    editor_element = QgsAttributeEditorField(
                        feature_name, field_index, current_container[-1]
                    )

                    if (
                        editor_widget.type() != "Hidden"
                        and feature_label.find("${") >= 0
                    ):
                        # Data-defined label
                        prop = QgsProperty()
                        prop.setExpressionString(
                            self.convert_label_expression(feature_label)
                        )
                        props = QgsPropertyCollection()
                        props.setProperty(
                            QgsEditFormConfig.DataDefinedProperty.Alias, prop
                        )
                        current_editor_form[-1].setDataDefinedFieldProperties(
                            feature_name, props
                        )

                    if feature_type == "calculate" or feature_type == "hidden":
                        editor_element.setShowLabel(editor_widget.type() != "Hidden")
                        current_editor_form[-1].setReadOnly(field_index, True)
                    elif (
                        feature_type == "today"
                        or feature_type == "start"
                        or feature_type == "end"
                        or feature_type == "username"
                        or feature_type == "email"
                    ):
                        editor_element.setShowLabel(False)
                        current_editor_form[-1].setReadOnly(field_index, True)

                        if feature_type == "today":
                            current_layer[-1].setDefaultValueDefinition(
                                field_index,
                                QgsDefaultValue(
                                    "format_date(now(), 'yyyy-MM-dd')", False
                                ),
                            )
                        elif feature_type == "start" or feature_type == "end":
                            current_layer[-1].setDefaultValueDefinition(
                                field_index,
                                QgsDefaultValue(
                                    "format_date(now(), 'yyyy-MM-dd hh:mm:ss')",
                                    feature_type == "end",
                                ),
                            )
                        elif feature_type == "username":
                            current_layer[-1].setDefaultValueDefinition(
                                field_index, QgsDefaultValue("@cloud_username", False)
                            )
                        elif feature_type == "email":
                            current_layer[-1].setDefaultValueDefinition(
                                field_index, QgsDefaultValue("@cloud_useremail", False)
                            )
                    elif self.survey_read_only_index >= 0:
                        field_read_only = (
                            str(feature.attribute(self.survey_read_only_index))
                            .strip()
                            .lower()
                            if feature.attribute(self.survey_read_only_index)
                            else ""
                        )
                        current_editor_form[-1].setReadOnly(
                            field_index, field_read_only == "yes"
                        )

                    if relevant_container:
                        relevant_container.addChildElement(editor_element)
                        current_container[-1].addChildElement(relevant_container)
                    else:
                        current_container[-1].addChildElement(editor_element)

                    current_editor_form[-1].setLabelOnTop(field_index, True)

                field_trigger = (
                    str(feature.attribute(self.survey_trigger_index)).strip()
                    if self.survey_trigger_index >= 0
                    and feature.attribute(self.survey_trigger_index)
                    else ""
                )
                if field_trigger != "":
                    self.warning.emit(
                        "Unsupported trigger option for {}, ignored".format(
                            feature_name
                        )
                    )

                field_calculation = (
                    str(feature.attribute(self.survey_calculation_index)).strip()
                    if self.survey_calculation_index >= 0
                    and feature.attribute(self.survey_calculation_index)
                    else ""
                )
                field_default = (
                    str(feature.attribute(self.survey_default_index)).strip()
                    if self.survey_default_index >= 0
                    and feature.attribute(self.survey_default_index)
                    else ""
                )
                if field_calculation != "":
                    current_layer[-1].setDefaultValueDefinition(
                        field_index,
                        QgsDefaultValue(
                            self.convert_expression(field_calculation),
                            feature_type == "calculate" or feature_type == "hidden",
                        ),
                    )
                elif field_default != "":
                    if "${last-saved" not in field_default:
                        is_digit = field_default.replace(".", "", 1).isdigit()
                        current_layer[-1].setDefaultValueDefinition(
                            field_index,
                            QgsDefaultValue(
                                field_default
                                if is_digit
                                else "'{}'".format(field_default),
                                False,
                            ),
                        )

                # project-wide max-pixels handling
                if feature_type == "image" and self.survey_parameters_index >= 0:
                    parameters = str(feature.attribute(self.survey_parameters_index))
                    image_max_pixels = re.search(
                        "max-pixels=\s*([0-9]+)", parameters, flags=re.IGNORECASE
                    )
                    image_max_pixels = (
                        int(image_max_pixels.group(1)) if image_max_pixels else 0
                    )
                    if image_max_pixels > 0:
                        if settings_max_pixels > -1:
                            if settings_max_pixels == 0:
                                # first max-pixels definition, adopt value
                                settings_max_pixels = image_max_pixels
                            elif settings_max_pixels != image_max_pixels:
                                # multiple max-pixels definition, adopt the largest value
                                settings_max_pixels = max(
                                    settings_max_pixels, image_max_pixels
                                )
                                self.warning.emit(
                                    self.tr(
                                        "Due to the presence of a mix of image attributes having max-pixels parameter of varying values, the largest max-pixels value will be applied"
                                    )
                                )
                        else:
                            self.warning.emit(
                                self.tr(
                                    "Due to the presence of a mix of image attributes having defined and undefined max-pixels parameter, the parameter has been ignored"
                                )
                            )
                    elif settings_max_pixels >= 0:
                        # image with missing max-pixels, prevent maximum value
                        if settings_max_pixels > 0:
                            self.warning.emit(
                                self.tr(
                                    "Due to the presence of a mix of image attributes having defined and undefined max-pixels parameter, the parameter has been ignored"
                                )
                            )
                        settings_max_pixels = -1

            elif (
                feature_type == "geopoint"
                or feature_type == "geotrace"
                or feature_type == "geoshape"
                or feature_type == "start-geopoint"
                or feature_type == "start-geotrace"
                or feature_type == "start-geoshape"
            ):
                continue
            else:
                type_details = str(feature.attribute(self.survey_type_index)).split(" ")
                type_details[0] = type_details[0].lower()
                if (
                    type_details[0] not in self.FIELD_TYPES
                    and type_details[0] not in self.METADATA_TYPES
                ):
                    self.warning.emit(
                        self.tr("Unsupported type {}, skipping".format(feature_type))
                    )

        current_layer[0].setEditFormConfig(current_editor_form[0])

        if settings_max_pixels > 0:
            self.output_project.writeEntry(
                "qfieldsync", "maximumImageWidthHeight", settings_max_pixels
            )

        output_project_file = str(
            os.path.join(output_directory, settings_filename + ".qgz")
        )
        self.output_project.writeProject.connect(self.process_project_write)
        self.output_project.write(output_project_file)

        survey_extent = None
        if (
            self.geometries
            and current_layer[0].geometryType() != Qgis.GeometryType.Null
            and current_layer[0].geometryType() != Qgis.GeometryType.Unknown
        ):
            if current_layer[0].geometryType() == QgsWkbTypes.geometryType(
                self.geometries.wkbType()
            ):
                current_layer[0].startEditing()

                request = QgsFeatureRequest()
                request.setDestinationCrs(
                    current_layer[0].crs(), self.output_project.transformContext()
                )
                geometries_iterator = self.geometries.getFeatures(request)
                for feature in geometries_iterator:
                    output_features = QgsVectorLayerUtils.makeFeatureCompatible(
                        feature,
                        current_layer[0],
                        QgsFeatureSink.SinkFlag.RegeneratePrimaryKey,
                    )
                    if output_features:
                        current_layer[0].addFeature(
                            output_features[0], QgsFeatureSink.Flag.FastInsert
                        )

                current_layer[0].commitChanges()
                if not current_layer[0].extent().isEmpty():
                    survey_extent = current_layer[0].extent()
            else:
                self.warning.emit(
                    self.tr(
                        "The geometries' type does not match the output survey layer, skipping"
                    )
                )

        if not self.extent.isEmpty():
            survey_extent = self.extent
        elif survey_extent:
            transform = QgsCoordinateTransform(
                current_layer[0].crs(),
                self.output_project.crs(),
                self.output_project.transformContext(),
            )
            try:
                survey_extent = transform.transformBoundingBox(survey_extent)
                if (
                    self.output_project.crs().mapUnits() != Qgis.DistanceUnit.Unknown
                    and self.output_project.crs().mapUnits()
                    != Qgis.DistanceUnit.Degrees
                ):
                    # Insure the initial project extent is not too zoomed in
                    if survey_extent.width() < 200:
                        padding = (200 - survey_extent.width()) / 2
                        survey_extent.setXMinimum(survey_extent.xMinimum() - padding)
                        survey_extent.setXMaximum(survey_extent.xMaximum() + padding)
                    if survey_extent.height() < 200:
                        padding = (200 - survey_extent.height()) / 2
                        survey_extent.setYMinimum(survey_extent.yMinimum() - padding)
                        survey_extent.setYMaximum(survey_extent.yMaximum() + padding)

                    survey_extent.scale(1.05)
                    self.output_extent = survey_extent
            except QgsCsException:
                survey_extent = None

        if not survey_extent:
            if self.output_project.crs().authid() == "EPSG:3857":
                survey_extent = QgsRectangle(-9.88, 33.41, 40.97, 61.11)
            else:
                survey_extent = self.output_project.crs().bounds()
                if survey_extent.width() < survey_extent.height():
                    survey_extent.setYMinimum(
                        survey_extent.yMinimum()
                        + survey_extent.height() / 2
                        - survey_extent.width() / 2
                    )
                    survey_extent.setYMaximum(
                        survey_extent.yMinimum()
                        + survey_extent.height() / 2
                        + survey_extent.width() / 2
                    )
                else:
                    survey_extent.setXMinimum(
                        survey_extent.xMinimum()
                        + survey_extent.width() / 2
                        - survey_extent.height() / 2
                    )
                    survey_extent.setXMaximum(
                        survey_extent.xMinimum()
                        + survey_extent.width() / 2
                        + survey_extent.height() / 2
                    )

            transform = QgsCoordinateTransform(
                QgsCoordinateReferenceSystem("EPSG:4326"),
                self.output_project.crs(),
                self.output_project.transformContext(),
            )
            survey_extent = transform.transformBoundingBox(survey_extent)

        self.output_extent = survey_extent

        if self.output_project.crs().authid() == "EPSG:3857":
            # Display coordinates in WGS84 to provide a more useful experience for the average person
            self.output_project.displaySettings().setCoordinateType(
                Qgis.CoordinateDisplayType.CustomCrs
            )
            self.output_project.displaySettings().setCoordinateCustomCrs(
                QgsCoordinateReferenceSystem("EPSG:4326")
            )

        output_project_file = str(
            os.path.join(output_directory, settings_filename + ".qgz")
        )
        self.output_project.writeProject.connect(self.process_project_write)
        self.output_project.write(output_project_file)

        return output_project_file
