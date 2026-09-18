"""Registry of valid Appian SAIL functions, components, and type casts.

Built from the official Appian 26.8 documentation. Used by the SAIL validator
to detect hallucinated (non-existent) functions.
"""

from __future__ import annotations

ARRAY_FUNCTIONS = frozenset({
    "a!flatten", "a!update", "append", "index", "insert", "joinarray",
    "ldrop", "rdrop", "length", "remove", "reverse", "where",
    "wherecontains", "updatearray", "difference", "intersection", "union",
    "distinct", "sort", "enumerate", "merge", "tointeger",
})

BASE_CONVERSION_FUNCTIONS = frozenset({
    "bin2dec", "dec2bin", "hex2dec", "dec2hex", "oct2dec", "dec2oct",
    "bin2hex", "bin2oct", "hex2bin", "hex2oct", "oct2bin", "oct2hex",
})

CONVERSION_FUNCTIONS = frozenset({
    "toboolean", "tointeger", "todecimal", "tostring", "todate",
    "todatetime", "totime", "todocument", "tofolder", "tocommunity",
    "toknowledgecenter", "toemailaddress", "toemailrecipient",
    "displayvalue", "externalize", "internalize", "tointervalds",
    "touniformstring", "torecord", "topeople", "touser", "togroup",
    "tonumber",
})

DATE_TIME_FUNCTIONS = frozenset({
    "date", "datetime", "time", "now", "today", "day", "month", "year",
    "hour", "minute", "second", "milli", "dayofyear", "isleapyear",
    "daysinmonth", "edate", "eomonth", "days360", "networkdays",
    "lastndays", "a!addDateTime", "calisworkday", "calisworktime",
    "calworkdays", "calworkhours", "gmt", "local", "intervalds",
    "datevalue", "datetext", "timevalue", "weekday", "weeknum",
})

CUSTOM_RECORD_FIELD_FUNCTIONS = frozenset({
    "a!customFieldConcat", "a!customFieldSum", "a!customFieldMultiply",
    "a!customFieldDivide", "a!customFieldSubtract", "a!customFieldMatch",
    "a!customFieldCondition", "a!customFieldLogicalExpression",
    "a!customFieldDateDiff", "a!customFieldDefaultValue",
})

CONNECTOR_FUNCTIONS = frozenset({
    "a!httpAuthenticationBasic", "a!httpHeader", "a!httpQueryParameter",
    "a!httpFormPart", "a!scsField", "a!wsConfig", "a!wsHttpCredentials",
    "a!wsHttpHeaderField", "a!wsUsernameToken", "a!wsUsernameTokenScs",
    "a!verifyRecaptcha",
})

LOGIC_FUNCTIONS = frozenset({
    "if", "and", "or", "not", "a!match", "isnull", "a!defaultValue",
    "choose", "reject", "apply", "reduce",
})

TEXT_FUNCTIONS = frozenset({
    "char", "charindex", "clean", "cleanwith", "code", "concat",
    "contains", "endswith", "exact", "find", "fixed", "initcap", "left",
    "len", "lower", "mid", "padleft", "padright", "proper", "repeat",
    "replace", "replaceb", "right", "rindex", "search", "split",
    "startswith", "strip", "stripwith", "substitute", "text", "trim",
    "upper", "urlwithparameters", "urlencode", "urldecode",
})

MATH_FUNCTIONS = frozenset({
    "abs", "average", "ceiling", "combin", "exp", "fact", "floor",
    "int", "ln", "log", "max", "min", "mod", "power", "product",
    "quotient", "rand", "round", "rounddown", "roundup", "sign",
    "sqrt", "sum", "sumsq", "trunc", "pi", "even", "odd",
    "gcd", "lcm", "median", "stdev", "var",
})

PEOPLE_FUNCTIONS = frozenset({
    "a!groupMembers", "group", "isusernametaken", "loggedInUser",
    "getdistinctusers", "getprocessmodelcreator", "user",
    "supervisor", "subordinates", "isUserMemberOfGroup",
    "todisplayvalue", "topeople", "touser", "togroup",
    "a!userRecordIdentifier", "a!groupRecordIdentifier",
})

SYSTEM_FUNCTIONS = frozenset({
    "a!localVariables", "a!forEach", "a!aggregationFields",
    "a!grouping", "a!measure", "a!pagingInfo", "a!sortInfo",
    "a!queryFilter", "a!queryLogicalExpression", "a!queryColumn",
    "a!querySelection", "a!queryRecordType", "a!recordData",
    "a!recordFilterList", "a!recordFilterListOption",
    "a!recordFilterDateRange", "a!recordFilterChoices",
    "a!relatedRecordData", "a!record",
    "a!save", "a!refreshVariable", "a!refreshOnReferencedVarChange",
    "a!refreshOnVarChange", "a!refreshAfter", "a!refreshAlways",
    "a!refreshInterval", "a!refreshNever",
    "a!isNotNullOrEmpty", "a!isNullOrEmpty",
    "a!keys", "a!urlWithParameters",
    "a!toJson", "a!fromJson",
    "a!map", "a!typeReference",
    "a!startProcess", "a!submitUploadedFiles",
    "todatasubset", "topaginginfo",
    "a!queryEntity", "a!entityData", "a!entityDataIdentifiers",
    "a!dataSubset", "a!listType", "a!recordType",
    "property", "typeof", "typename", "isnull",
    "a!iconIndicator", "a!iconNewsEvent",
})

DOCUMENT_FUNCTIONS = frozenset({
    "a!docExtractionResult", "a!docExtractionStatus",
    "document", "folder", "todocument", "tofolder",
})

PROCESS_FUNCTIONS = frozenset({
    "a!startProcess", "a!processInfo",
    "getprocessmodelproperty", "processmodelbyid",
    "processmodelfolder",
})

# -- SAIL COMPONENTS (a!componentName) -- from official 26.8 docs --

LAYOUT_COMPONENTS = frozenset({
    "a!formLayout", "a!headerContentLayout", "a!paneLayout",
    "a!wizardLayout", "a!wizardStepLayout",
    "a!billboardLayout", "a!boxLayout", "a!cardLayout",
    "a!columnsLayout", "a!columnLayout", "a!sectionLayout",
    "a!sideBySideLayout", "a!sideBySideItem",
    "a!stampLayout", "a!milestoneBarLayout",
    "a!richTextLayout", "a!splitPaneLayout",
    "a!tabLayout", "a!tabContent",
})

INPUT_COMPONENTS = frozenset({
    "a!textField", "a!paragraphField", "a!integerField",
    "a!decimalField", "a!dateField", "a!dateTimeField", "a!timeField",
    "a!fileUploadField", "a!encryptedTextField",
    "a!currencyField", "a!percentageField",
    "a!floatingPointField",
})

SELECTION_COMPONENTS = frozenset({
    "a!dropdownField", "a!multipleDropdownField",
    "a!checkboxField", "a!radioButtonField",
    "a!toggleField", "a!booleanField",
    "a!cardChoiceField", "a!chipField",
    "a!dynamicLink", "a!submitLink", "a!processTaskLink",
    "a!buttonLayout", "a!buttonWidget", "a!buttonArrayLayout",
    "a!safeLink", "a!authorizationLink",
})

DISPLAY_COMPONENTS = frozenset({
    "a!imageField", "a!documentImage", "a!userImage", "a!webImage",
    "a!richTextDisplayField", "a!richTextItem",
    "a!richTextIcon", "a!richTextImage", "a!richTextBulletedList",
    "a!richTextNumberedList", "a!richTextListItem",
    "a!richTextHeader", "a!richTextLink",
    "a!gaugeField", "a!gaugePercentage", "a!gaugeFraction",
    "a!kpiField", "a!milestoneField", "a!progressBarField",
    "a!tagField", "a!tagItem",
    "a!videoField", "a!webContentField",
    "a!stampField",
})

GRID_COMPONENTS = frozenset({
    "a!gridLayout", "a!gridLayoutHeaderCell", "a!gridLayoutRow",
    "a!gridLayoutCell",
    "a!gridField",
    "a!gridColumn", "a!gridColumnConfig",
    "a!gridSelection", "a!gridSelectedItem",
    "a!gridTextColumn", "a!gridImageColumn", "a!gridIconColumn",
    "a!recordGrid",
})

CHART_COMPONENTS = frozenset({
    "a!areaChartField", "a!barChartField", "a!columnChartField",
    "a!lineChartField", "a!pieChartField", "a!scatterChartField",
    "a!chartSeries", "a!chartReferenceLines", "a!chartReferenceLine",
})

PICKER_COMPONENTS = frozenset({
    "a!pickerFieldUsers", "a!pickerFieldGroups",
    "a!pickerFieldRecords", "a!pickerFieldDocuments",
    "a!pickerFieldCustom", "a!pickerFieldSuggestions",
})

BROWSER_COMPONENTS = frozenset({
    "a!documentBrowserField", "a!folderBrowserField",
    "a!hierarchyBrowserField", "a!orgChartField",
})

RECORD_ACTION_COMPONENTS = frozenset({
    "a!recordActionField", "a!recordActionItem",
    "a!relatedActionField",
})

LINK_COMPONENTS = frozenset({
    "a!documentDownloadLink", "a!newsLink", "a!reportLink",
    "a!processLink", "a!taskLink", "a!startProcessLink",
    "a!userRecordLink", "a!recordLink", "a!safeLink",
})

MISC_COMPONENTS = frozenset({
    "a!localVariables", "a!forEach",
    "a!refreshVariable", "a!save",
    "a!showWhen", "a!isPageWidth",
    "a!caseWhenLayout",
})

# -- KNOWN HALLUCINATED FUNCTIONS (DO NOT EXIST) --
HALLUCINATED_FUNCTIONS = frozenset({
    "a!filter", "a!forEachItem", "a!reduce", "a!if",
    "a!concat", "a!split", "a!contains",
    "a!length", "a!append", "a!remove",
    "a!map",  # a!map exists for creating maps but NOT for array mapping
    "a!sort", "a!distinct", "a!first", "a!last",
    "a!isEmpty", "a!isNotEmpty",
    "a!toInteger", "a!toString", "a!toDecimal",  # wrong casing — these are tointeger, tostring, etc.
    "a!localVariable",  # wrong — it's a!localVariables (plural)
    "a!queryRecord",  # wrong — it's a!queryRecordType
    "a!recordFilter",  # wrong — it's a!queryFilter
})

# Consolidate all valid functions
ALL_VALID_FUNCTIONS: frozenset[str] = (
    ARRAY_FUNCTIONS
    | BASE_CONVERSION_FUNCTIONS
    | CONVERSION_FUNCTIONS
    | DATE_TIME_FUNCTIONS
    | CUSTOM_RECORD_FIELD_FUNCTIONS
    | CONNECTOR_FUNCTIONS
    | LOGIC_FUNCTIONS
    | TEXT_FUNCTIONS
    | MATH_FUNCTIONS
    | PEOPLE_FUNCTIONS
    | SYSTEM_FUNCTIONS
    | DOCUMENT_FUNCTIONS
    | PROCESS_FUNCTIONS
)

ALL_VALID_COMPONENTS: frozenset[str] = (
    LAYOUT_COMPONENTS
    | INPUT_COMPONENTS
    | SELECTION_COMPONENTS
    | DISPLAY_COMPONENTS
    | GRID_COMPONENTS
    | CHART_COMPONENTS
    | PICKER_COMPONENTS
    | BROWSER_COMPONENTS
    | RECORD_ACTION_COMPONENTS
    | LINK_COMPONENTS
    | MISC_COMPONENTS
)

ALL_VALID_IDENTIFIERS: frozenset[str] = ALL_VALID_FUNCTIONS | ALL_VALID_COMPONENTS

# Type cast functions (subset of conversion functions used as typecasts)
TYPE_CAST_FUNCTIONS = frozenset({
    "toboolean", "tointeger", "todecimal", "tostring", "todate",
    "todatetime", "totime", "todocument", "tofolder", "tonumber",
    "touniformstring", "topeople", "touser", "togroup", "torecord",
})

# Appian SDK Component Plug-in JS API (for reference/validation)
COMPONENT_PLUGIN_JS_API = {
    "Appian.Component.onNewValue": "Register callback for parameter updates",
    "Appian.Component.saveValue": "Save parameter value back to SAIL",
    "Appian.Component.setValidations": "Set/clear validation messages",
    "Appian.Component.invokeClientApi": "Call connected system server-side logic",
    "Appian.Component.getAriaLabelledBy": "Get label ID for accessibility",
    "Appian.Component.getAriaDescribedBy": "Get instruction/validation IDs",
    "Appian.getLocale": "Get user locale",
    "Appian.getAccentColor": "Get environment accent color hex",
}

# Supported component plug-in parameter types
COMPONENT_PLUGIN_PARAM_TYPES = frozenset({
    "Boolean", "Decimal", "Integer", "Text", "Dictionary",
    "Variant", "ConnectedSystem", "TypedValue",
    "Boolean?list", "Decimal?list", "Integer?list", "Text?list",
    "Dictionary?list", "Variant?list", "TypedValue?list",
})

# Inherited common parameters (auto-available on all component plug-ins)
COMPONENT_PLUGIN_COMMON_PARAMS = frozenset({
    "label", "labelPosition", "instructions", "helpTooltip",
    "required", "disabled", "validations", "height", "showWhen",
})
