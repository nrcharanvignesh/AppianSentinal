# Appian Designer UI reference

Every statement here comes from official Appian 26.8 documentation. Anything the
documentation does not state is listed under "Not verified" and must not be
invented: guessing at Appian's internals is the same mistake this project
refuses to let the model make with SAIL.

## Navigation pane

Environment level: `Applications`, `Objects`, `Packages`, `Deploy`, `Monitor`,
`Users`. Inside an application: `Plan`, `Explore`, `Build`, `Packages`,
`Deploy`, `Monitor`.

Source: https://docs.appian.com/suite/help/26.8/common-view-elements.html

## Header bar

Back arrow (inside an application), context icon, application name, quick
search, settings menu, navigation menu, user menu.

Source: https://docs.appian.com/suite/help/26.8/common-view-elements.html

## Build view

Tabs: `BOARD` (only when Plan is enabled), `ALL OBJECTS`, `PLUG-INS`,
`UNREFERENCED OBJECTS`.

The objects grid has exactly these columns, in this order:

1. selection checkbox (unnamed)
2. object type icon (unnamed)
3. `Name`
4. `Description`
5. `Last Modified`

`Last Modified` combines the developer and the timestamp, and is the default
sort. There is no `Type` text column, no `Security` column, and no `Warnings`
column in this grid.

Search matches name, description, UUID, ID, and expression. Filters are object
type, developer who last modified, and date last modified. The grid offers
`flat view` and `hierarchical view`.

Toolbar: `NEW`, `ADD EXISTING`, Duplicate, `MOVE`, `REMOVE FROM APP`, `DELETE`,
`SECURITY`, `DEPENDENTS`, `PRECEDENTS`, `ADD TO PACKAGE`.

Source: https://docs.appian.com/suite/help/26.8/build-view.html

## Object type categories and colors

The documentation verifies a colour per category, not a hex value.

| Category | Colour | Types |
|---|---|---|
| Data | orange | Business Process, Data Store, Data Type, Record Type |
| Process | dark blue | Process Model, Process Report, Robotic Task, Robot Pool |
| User | Appian blue | Control Panel, Control Panel Hierarchy Item, Dashboard, Interface, Portal, Report, Site, Tempo Report |
| Rule | purple | AI Agent, AI Skill, Constant, Decision, Expression Rule, Translation Set |
| Integration | bright green | Connected System, Integration, Web API, Event Consumer |
| Group | red | Group, Group Type |
| Content management | dark green | Document, Document Folder, Knowledge Center |
| Notification | dark yellow | Feed |

A Rule Folder takes the rule colour and a Process Model Folder takes the
process colour.

Source: https://docs.appian.com/suite/help/26.8/design-objects.html

## Design guidance

Exactly two levels:

- `Warning`: yellow triangle. Likely runtime error or unexpected behaviour.
  Cannot be dismissed.
- `Recommendation`: gray lightbulb. Best-practice concern. Can be dismissed.

A red icon is a syntax error, not a third severity. Guidance is suppressed
until syntax errors are fixed.

Verified warning rules include invalid keyword syntax, invalid parameter,
invalid record field reference, missing domain prefix, and outdated data type
reference. Verified recommendations include improperly scoped variable, unused
local variable, unused rule input, missing primary key, multiple levels of
nesting, and primitive type array.

Source: https://docs.appian.com/suite/help/26.8/appian-recommendations.html

## Expression editor

Toolbar: `Format expression`, `Decrease Indent`, `Increase Indent`,
`Show/Hide Indent Guide`, `Comment`, `Find`, `Replace`, `View Domains`,
`View Functions`, `View Icons`, `Create Constant`,
`Save Selected Expression As...`, `Launch the Query Editor`.

Layout is toolbar, editing pane, documentation pane. Autocomplete covers
functions, function variables, rules, data types, keywords, variables, and
valid parameter values across the `fn!`, `a!`, `fv!`, `rule!`, `type!`,
`local!`, `ri!`, and `rv!` domains. A syntax error shows a red warning icon in
the editor's upper-left corner with details on hover.

Source: https://docs.appian.com/suite/help/26.8/expression-editor.html

## Expression rule testing

The default `Ad Hoc Test` view has `Test Inputs`, local variable values, and
`Test Output`. `TEST RULE` evaluates. Output renders as a formatted map, a raw
list, or an expression. Saved test case statuses are `Test passed`,
`Test failed: test output did not match asserted output`,
`Test failed: assertion expression returned false`, `Test failed to run`, and
`Test returned an error`.

Source: https://docs.appian.com/suite/help/26.8/Expression_Rules.html

## Interface designer

Palette on the left with `Components`, `Patterns`, and `Design Library`
sections. Central live view. Right configuration panel with `Rule Inputs`,
`Local Variables`, and `Component Configuration`, whose fields group under
`Content`, `Data`, `Behavior`, and `Styling`. Modes are `AI mode`,
`Design mode`, and `Expression mode`. Hover highlights pink, selection
highlights blue.

Source: https://docs.appian.com/suite/help/26.8/working_in_design_mode.html

## Monitor

Health Dashboard cards: Process Activity, Process Model Metrics, Record
Response Times, Record Sync Status, Security Warnings, Test Health,
Unreferenced Objects, plus an `Appian Design Guidance` grid whose columns are
`Name`, `Warnings and Recommendations`, and `Last Modified`.

Health Check is a separate, broader environment analysis with risk levels
`High`, `Medium`, `Low`, `Info`, and `Unknown`. Do not label object-level
findings "Health Check".

Sources: https://docs.appian.com/suite/help/26.8/monitoring_view.html and
https://docs.appian.com/suite/help/26.8/health-check.html

## Typography

`Open Sans` is the standard Appian web typeface.

Source: https://docs.appian.com/suite/help/26.8/css-profile-typefaces.html

## Not verified, do not invent

Hex values for the object category colours, glyph geometry for each object type
icon, Designer header height, navigation width, grid row height, border
colours, shadows, and expression-editor token colours. The documented site
accent `#1d659c` is a Sites default, not proof of a Designer shell colour.
