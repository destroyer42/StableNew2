StableNew GUI Modernization: Workflow Priorities, Figma Design Kit, and Courses of Action
Executive summary
Recommendation: adopt COA A — PySide6 with Qt Widgets as the primary desktop shell and selective Qt Quick/QML surfaces.

StableNew is no longer a simple parameter form around an image-generation backend. Its current GUI coordinates prompt authoring, deterministic Preview-to-queue admission, generation profiles, durable job history, image review and masking, photo optimization, multiple video workflows, guided learning experiments, runtime configuration, media inspection, and application lifecycle behavior. The repository already recognizes this complexity by separating the canonical Tk host in src/gui/ from toolkit-neutral adapters in src/gui_v2/, while explicitly reserving that boundary for a possible future toolkit migration.

The current architecture also shows why a migration cannot be treated as a widget replacement. build_v2_app() constructs a Tk root, a TkUiDispatcher, AppStateV2, AppController, and MainWindowV2, then injects the window back into the controller; even watchdog attachment depends on a heartbeat installed by the GUI host. AppStateV2 has a useful subscribe/notify architecture, but it still imports GuiInvoker, and AppController retains direct main_window references in some paths.

The good news is that StableNew has already created many of the right seams. UiDispatcher is a toolkit-neutral protocol; task navigation is a pure contract with stable tab IDs; several workflow projections and presentation decisions are toolkit-independent; and the GUI ownership rules explicitly prohibit the GUI from becoming a second queue, runner, prompt compiler, or durable state authority. This makes an incremental migration plausible without rewriting the generation engine.

From a technology standpoint, PySide6 is viable for the project's current Python generation. PySide6 6.12.0 was released on October 8, 2026; PyPI lists Python 3.14 support and provides a Windows x86-64 abi3 wheel. Qt for Python is the official Qt Python binding and is available under LGPLv3/GPLv3 or a commercial Qt license. Qt's deployment tooling now uses standalone packaging by default and can explicitly control QML/plugin inclusion. 

The migration priority should not mirror the visible tab order. The sequence should be driven by architecture criticality and cost of behavioral regression:

Priority	StableNew surface	Why it belongs here	Migration risk
P0	Shared shell / state / dispatch	Everything depends on lifecycle, navigation, state projection, cancellation, thread delivery and shutdown	Very high architectural
P0	Create	Core intent → Preview → queue workflow; generation settings and model/profile behavior must remain exact	High
P0	History / queue	Durable truth, replay lineage and operator confidence; cannot tolerate duplicate state	High
P0/P1	Settings	Controls backend/runtime behavior and persistent startup configuration	High
P1	Edit	Mask coordinates, zoom/pan, overlays, reprocess lineage and media lifecycle are technically difficult	Very high UI
P1	Motion	Playback, sequence authoring, asynchronous preparation and external/runtime resources	Very high UI/runtime
P2	Learn	Rich workflow, but much of its presentation is already driven by pure projections	Medium-high
P3	Advanced	Character Training is explicitly HOLD and should remain so	Low product priority / medium porting

This is a migration-risk prioritization, not a claim about user-frequency telemetry; no usage analytics were available to establish which screen operators visit most often. The repository does, however, identify Pipeline as the default workspace and preserves nine stable workspace IDs grouped into Create, Edit, Motion, Learn and Advanced.

The design recommendation is to retain StableNew's existing visual identity rather than invent a new brand during the toolkit migration. The repository already has a semantic token system: dark #121212 page background, #1E1E1E elevated surfaces, #FFC805 primary accent, Segoe UI typography, 4/8/12-based spacing, explicit semantic notice roles, and focus/contrast rules. Those values should become Figma Variables, Qt semantic tokens, and a QML singleton from one canonical specification rather than being independently recreated in three systems.

The principal technology decision is therefore:

Qt Widgets should own the shell, forms, tables, settings, prompt editing, history, model browser and precision editing canvases. QML should be reserved for places where a retained-mode animated scene actually produces a UX advantage: timelines, animated media controls, sophisticated compare surfaces or future visual workflow editors.

That choice is especially important because embedding Qt Quick in a Widgets application through QQuickWidget is not free: Qt documents an additional offscreen render pass and states that QQuickWidget disables the threaded Qt Quick render loop. QML should therefore be selective and bounded, not sprinkled throughout the Widgets hierarchy. 

A full parity migration under COA A is best planned as approximately 20–32 engineering weeks, including Windows qualification and packaging, for one experienced developer working sequentially with substantial automation/AI assistance. COA B, a Qt Quick-first application, is estimated at 28–42 engineering weeks because more desktop controls, docking behavior, editing surfaces and accessibility behavior would need custom implementation. These are planning estimates, not measured delivery durations; M0 should narrow them through actual Windows prototypes.

The research in this report used current remote repository source evidence, but no StableNew executable, local Windows checkout, GPU workload, installer or Figma file was exercised. Consequently, startup time, idle RAM, GUI GPU/VRAM consumption, codec behavior, 100%/150% multi-monitor DPI behavior, deployment size and screen-reader behavior remain runtime qualification items rather than verified results.

Workflow priorities and migration evidence
StableNew's current navigation contract identifies nine canonical workspaces. Create contains Prompt and Pipeline; Edit contains Review and Photo Optimize; Motion contains Video Workflow, SVD Img2Vid and Movie Clips; Learn contains Learning; Advanced contains Character Training, which is explicitly marked HOLD. Pipeline is the default workspace, historic numeric tab indexes remain backward-compatible, and stable string IDs are now authoritative.

History is not currently a separate canonical navigation tab: the ownership map states that Job History remains within Pipeline. For the modernization design, I recommend making History a first-class shell destination visually while preserving its underlying authority and stable compatibility behavior until an explicitly approved product change says otherwise. In other words, Figma may depict History as a prominent left-rail destination, but M2 implementation should initially route it to the existing history surface rather than silently changing persistence semantics or navigation contracts.

Prioritized workflow inventory
Priority	Workflow	Current functional owner / evidence	Primary migration risk	Required acceptance evidence
P0	Shared shell	MainWindowV2, AppStateV2, task-navigation contract, TkUiDispatcher; active Tk host is src/gui/ and neutral adapters are src/gui_v2/.	Event-loop ownership, subscriptions, window/controller coupling, persisted selected-tab compatibility, shutdown, detached media	Stable IDs resolve identically; old selected_index fallback still works; subscription disposal verified; no stale callback mutates destroyed view; clean shutdown; same process/queue authority
P0	Create — Prompt	PromptTabFrame; PromptPack-oriented authoring and model-target behavior.	Rich prompt editing, target compatibility, LoRA/model browser, PromptPack state, optimizer handoffs	Same PromptPack loaded/saved; positive/negative prompt parity; target findings identical; keyboard editing/completion tests; no prompt construction moved into UI
P0	Create — Pipeline	PipelineTabFrame, Pipeline controller/presenters, AppState preview; Pipeline is current default workspace.	Highest-volume configuration surface; model/profile behavior; Preview staleness; queue admission	Given identical intent, Qt and Tk produce the same accepted Preview/NJR set; Add to Queue submits that accepted Preview, not a regenerated sample.
P0	History / queue	JobRepository is SQLite-backed queue/history authority; JobHistoryPanelV2 plus paged History browser.	Accidentally making Qt models authoritative, pagination/filter races, replay semantics	Same repository rows and status; paged/filter query parity; replay/resume creates new job identity and preserves parent lineage; no shadow history
P0/P1	Settings / profiles	EngineSettingsDialog, ConfigManager, generation-profile store; profiles intentionally separate from PromptPacks and engine settings.	Persistence compatibility, backend identity, restart-required settings, accidentally conflating settings sources	Byte/semantic compatibility of persisted config; source labels remain correct; restart-required values stay explicit; external runtimes never silently adopted
P1	Edit — Review	ReviewTabFrame is canonical reprocess workspace; mask editor has document/viewport model with brush, erase, undo/redo, clear, zoom and pan.	Pixel-coordinate transforms, mask alignment, content visibility, reprocess lineage	Golden-coordinate tests at multiple zooms/DPI; mask export pixel identity; undo/redo invariants; same reprocess intent and lineage; hide/show releases media correctly
P1	Edit — Photo Optimize	PhotoOptimizeTabFrame; shared media inspector supports independent Original/Candidate surfaces.	Independent baselines, sidecars, before/after state, asynchronous image load	Original and candidate remain independent; exact selected artifact preserved; store/sidecar persistence compatible; no stale async render after selection change
P1	Motion — Video Workflow	Video Workflow uses background probing and Tk dispatch; shared media inspection includes recent outputs.	Media decoder lifecycle, GPU resources, playback, runtime preflight, cancellation	Player stops/releases on hide/destroy; no leaked decoder; source and runtime status parity; queue submission remains existing authority
P1	Motion — SVD / Movie Clips	Ownership map identifies SVD media inspection and Movie Clips as file-list/assembly workspace rather than inline viewer.	Ordered media manipulation, batch sequence submission, progress, output handoffs	Deterministic sequence order; same one-queue admission semantics; interrupt/resume/replay parity; output paths unchanged
P2	Learn	Guided workflow is Design → Preview → Run → Compare → Rate; views render pure projections from src/learning/, while LearningController remains coordinator.	Experiment matrix presentation, high thumbnail volume, compare/rating state	Workflow gates identical; preview summary same; ratings/curation persistence unchanged; bounded thumbnail/cache behavior; no second execution path
P3	Advanced	Character Training is explicitly HOLD because no trainer is bundled.	A migration accidentally appearing to enable unsupported functionality	Same HOLD label and reason; no Run/Train execution path introduced; configuration remains readable if already persisted

Why Shared shell and Create come before the visually hardest screens
Edit and Motion are the hardest widgets to port, but they should not be the first production migration. The first architectural proof needs to establish that Qt can subscribe to existing projections, issue application intents, maintain exact Preview/queue semantics, survive view destruction and shut down without changing process ownership. Only after that is true does it make sense to invest in a mask editor or video timeline.

The repository already supports that strategy. UiDispatcher is a minimal toolkit-neutral contract containing invoke(fn), while the current implementation uses TkUiDispatcher; this gives M1 a natural place for a QtUiDispatcher.

AppStateV2 similarly has a valuable conceptual interface—named subscriptions, unsubscriptions, hot-runtime batching and shutdown notification suppression—but its direct GuiInvoker dependency means it is not yet entirely toolkit-independent. The ideal migration is therefore to retain its semantics while extracting its scheduler dependency, rather than replacing the state model wholesale.

Functional architecture to preserve
Qt Presentation Host
Widgets + selected QML

Intent / Command Ports

Read-only Projection Models

Application State / Projection Authority

Existing Controllers / Services

Compiler / Builders

Immutable NJR

JobService

SQLite Queue / History Authority

PipelineRunner

Artifacts / Results

Background query / media workers

QtUiDispatcher
queued GUI delivery

Selective QML surfaces



Show code
The key rule is dependency direction: Qt models are projections of application state, not repositories; views issue intent, not jobs; workers return immutable results/revisions to the GUI thread; and the existing queue/history lifecycle remains the only durable authority. That matches StableNew's current GUI ownership rules.

Figma-ready PySide6 and Qt/QML design kit
Component strategy
Qt provides a much stronger match for StableNew's desktop shape than Tk. QMainWindow explicitly supports central widgets and dock areas; QDockWidget supports docked or floating tool panels; QSplitter provides resizable panes; and Qt's model/view framework separates data from QListView, QTreeView and QTableView. 

For editing, Qt Graphics View is particularly relevant: QGraphicsScene and QGraphicsView provide item-based 2D scenes, event propagation, zoom/rotation and explicit mapping among item, scene and view coordinate systems. Those coordinate mapping facilities are a strong fit for StableNew's mask/outpaint requirements, where zoomed screen coordinates must resolve consistently to source-image pixels. 

For media, Qt Multimedia exposes QMediaPlayer and QVideoWidget on the Widgets side, while Qt Quick provides VideoOutput. For text-heavy prompt authoring, QPlainTextEdit provides a purpose-built plain text editor and can be augmented with QSyntaxHighlighter and QCompleter. 

Qt component mapping
StableNew UI need	Qt Widgets recommendation	Qt Quick/QML equivalent	Data/model binding	Recommended owner
Main desktop shell	QMainWindow	ApplicationWindow	Shell projection + command router	Widgets
Primary navigation	QListView or styled QToolButton rail + QStackedWidget	ListView + StackView	Stable tab-ID model	Widgets
Resizable workspaces	QSplitter	SplitView	Persist splitter state separately from business state	Either
Dockable inspector / queue / log	QDockWidget	Custom SplitView/Drawer/window	Read-only projection	Widgets
Prompt editor	QPlainTextEdit, QSyntaxHighlighter, QCompleter	TextArea + custom behavior	Prompt-document presenter	Widgets
Model browser	QListView/QTreeView	ListView/GridView	QAbstractListModel + filter proxy	Either
Generation profile strip	QComboBox, labels, disclosure widget	ComboBox, Pane, Column	Profile projection + commands	Widgets
Settings/form controls	QFormLayout, QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox, QSlider	Controls + layouts	Presenter/QObject properties	Widgets
Queue/history table	QTableView + QAbstractTableModel + proxy	TableView + headers	Repository-backed projection model	Widgets
Image/media inspector	QGraphicsView/QLabel depending complexity	Flickable + Image	Media-selection projection	Widgets initially
Mask/outpaint canvas	QGraphicsView + QGraphicsScene + pixmap/path items	Flickable + Image + Canvas/custom QQuickItem	Mask document separate from render object	Widgets
Comparison overlay	QGraphicsView items or paired views	QML scene/animated slider	Compare projection	Selective QML candidate
Video player	QMediaPlayer + QVideoWidget	MediaPlayer + VideoOutput	Media session object	Widgets baseline / QML candidate
Video timeline	Custom QGraphicsView timeline	Flickable/ListView + delegates	Sequence model	QML candidate
Learning experiment grid	QTableView/QListView + delegate thumbnails	GridView	Experiment result model	Widgets initially
Inline notice	Custom QFrame + labels	Custom Pane + Label	Notice projection	Both
Modal settings	QDialog, native file dialogs where appropriate	Dialog, FileDialog	Config command interface	Widgets
Diagnostics/log	QPlainTextEdit read-only or QTableView	ListView	Ring-buffer/log projection	Widgets
Detached media	Top-level QWidget/QDialog or dedicated window	Window	Same media session, new renderer	Either

QAbstractItemModel is unusually valuable here because the same Python model architecture can feed both Widgets views and QML views. Qt explicitly documents item models as underlying data for both QML item views and Widget item views, and QAbstractListModel exposes named roles to QML through roleNames(). 

That means StableNew should avoid writing separate “Widget history objects” and “QML history objects.” Instead:

StableNew DTOs / projections

Qt presentation adapter

QAbstractListModel

QAbstractTableModel

QListView / QTreeView

QML ListView / GridView

QTableView

QML TableView

StableNew semantic tokens

Figma Variables

Qt palette / QSS

QML Token Singleton

Command ports

Existing controllers/services



Show code
Figma token specification
StableNew's existing visual system is mature enough to become the starting Figma library rather than an interim theme. The active style guide identifies semantic ownership across design_system_v2.py, ui_tokens.py and theme_v2.py, and explicitly treats ui_tokens.py as the semantic source of truth.

Color variables
Figma variable	Existing value	Role
surface/page	#121212	Main application background
surface/elevated	#1E1E1E	Cards, panels, section surfaces
surface/tertiary	#161616	Secondary dark depth
surface/hover	#262626	Hover
surface/selected	#2B2B2B	Selected navigation/header
border/subtle	#2D2D2D	Card/input/divider edge
separator	#2A2A2A	Low-emphasis separators
accent/primary	#FFC805	Primary action, selected/focus semantics
accent/hover	#FFD94D	Primary hover
text/primary	#FFFFFF	Main text
text/muted	#CCCCCC	Supporting text
text/disabled	#777777	Disabled state
text/on-accent	#000000	Text on gold
danger/default	#D9363E	Destructive action
danger/hover	#C62F36	Destructive hover
status/success	#52C41A	Success semantic
status/warning	#D9A04A	Warning semantic
status/error	#FF4D4F	Error semantic
status/info	#4A90D9	Informational semantic

These values are already represented by the repository's raw and semantic token layers.

Gold should remain semantic, not decorative. The existing style guide reserves it for the primary action, selection/non-default hidden-content cues and keyboard focus. Preserving that rule will keep the new interface visually cleaner than simply making more components gold because Qt enables richer styling.

Typography and spacing
StableNew currently specifies Segoe UI and 9/10/11/12/14-point sizes, with current major layout metrics centered on 4, 8 and 12 units.

For Figma, define type tokens by semantic role rather than “H1/H2,” because this is a dense production desktop tool:

Token	Qt implementation	Figma 96-DPI reference	Use
type/caption	Segoe UI 9 pt	12 px	Metadata, compact counters
type/body	Segoe UI 10 pt	13.33 px	Standard controls/content
type/subheading	Segoe UI 11 pt bold	14.67 px	Group headings
type/heading	Segoe UI 12 pt bold	16 px	Card/workspace headings
type/emphasis	Segoe UI 14 pt bold	18.67 px	Sparse hero/state value only

The Figma pixel values are 96-DPI design references, not implementation constants. Qt should retain point-based font semantics and let Qt's high-DPI system handle device scaling. Qt's higher-level Widgets and Quick APIs operate in device-independent coordinates and automatically account for display density; image assets still require high-resolution handling. 

Recommended Figma spacing variables:

Token	Value	Purpose
space/1	4	Inline/icon gap
space/2	8	Control spacing
space/3	12	Card internals
space/4	16	Derived composition spacing
space/6	24	Major section separation
space/8	32	Large workspace separation

The canonical current semantic set already defines 4, 8, 12 and 24; 16 and 32 should be documented as composition extensions rather than silently replacing the existing token system.

Radii should use the current 4/8/12 values for small controls, cards and elevated dialogs respectively. Motion tokens can carry forward the existing 120/220/320 ms values for fast/base/slow interactions; most production controls should remain minimally animated.

Component variants for the Figma library
The Figma library should contain behavioral states, not just pretty master components. At minimum:

Component family	Required variants
Button	Primary / Secondary / Ghost / Danger × Default / Hover / Pressed / Focus / Disabled
Navigation item	Default / Hover / Selected / Disabled / HOLD / Notification badge
Text input	Empty / Filled / Focus / Error / Disabled / Read-only
Combo/model selector	Closed / Open / Selected / Loading / Unsupported / Error
Card	Default / Selected / Warning / Disabled / Collapsed
Disclosure	Collapsed / Expanded / Focused
Inline notice	Neutral / Info / Success / Warning / Error / Queued
Model row	Installed / Available / Active / Unsupported / Missing dependency / Loading
Profile strip	No profile / Research / Learning / Custom / Favorite / Modified
Table row	Default / Hover / Selected / Running / Failed / Complete / Disabled action
Media inspector	Loading / Hidden / Image / Video / Missing / Policy blocked / Detached
Mask toolbar	Select / Brush / Erase / Pan + active/inactive/focus variants
Timeline clip	Default / Selected / Processing / Failed / Missing source / Trimmed
Workflow step	Pending / Current / Complete / Blocked / Error
Progress	Determinate / Indeterminate / Paused / Failed
Runtime state	Ready / Starting / Busy / Degraded / Disconnected / Externally managed

The current StableNew style guide already requires visible semantic words for notices rather than color-only status and defines specific contrast expectations. Those requirements should be encoded in Figma component annotations and later automated accessibility tests.

Iconography and export specification
Use one consistent monochrome SVG icon family with 16, 20 and 24 logical-pixel frames; stroke weight and optical padding should be standardized in the Figma component library. State should come from semantic color tokens, not separate hard-coded colored SVG files. Avoid mixing platform-standard Qt icons with custom line icons in the same command surface because visual weight and metaphor can vary by OS.

The Figma handoff should specify:

Asset	Export
Icons	SVG with stable viewBox, vector paths, no text nodes
App icon	Master vector plus Windows .ico build derivative
Logos/illustrations	SVG where practical
Raster thumbnails/reference media	PNG, 1× and 2× only where raster is intrinsic
QML decorative assets	Prefer vector or scale-independent primitives
Tokens	Figma Variables plus machine-readable semantic token table
Component specs	Frame anatomy, padding, min size, state table, keyboard behavior, accessible name/description
Layouts	Desktop frames at 1366×768, 1440×900 and 1920×1080; annotate behavior rather than just coordinates

Qt's official deployment tooling expects a Windows .ico for the packaged application icon and explicitly tracks QML files and plugins in its deployment specification. 

Accessibility and DPI requirements
Moving to Qt creates a materially better accessibility foundation than the current Tk presentation. StableNew's current guide explicitly notes that its semantic notice roles do not produce a screen-reader accessibility tree under Tk. Qt, by contrast, provides accessible interfaces for standard Widgets and Qt Quick Controls, with custom-widget support through Qt's accessibility interfaces; QML also exposes accessibility metadata through Accessible. 

Acceptance should therefore include actual Windows UI Automation/screen-reader testing rather than merely assuming Qt makes the application accessible. Every custom canvas, timeline, media control and nonstandard delegate still needs meaningful names, roles, keyboard traversal and equivalent non-pointer actions. Qt's accessibility framework provides the mechanisms; StableNew must still implement the semantics. 

The existing manual test matrix of 1366×768 and 1920×1080 at 100% and 150% scale should be preserved and expanded to movement between monitors with different scale factors. Qt's high-DPI model is device-independent, but raw image buffers and pixel-exact mask documents require explicit distinction between source-image pixels, logical GUI coordinates and device pixels. 

Courses of action
COA A — Qt Widgets primary with selective QML surfaces
Recommended.

The application host becomes a QMainWindow. Dense desktop forms, data views, settings, queue/history, prompt authoring and precision image editing remain Widgets. QML is introduced only where its retained scene graph and animation model provide an identifiable operator benefit, primarily an advanced timeline or highly interactive comparison surface. Qt's own APIs directly support the Widgets shell pattern through QMainWindow, QDockWidget, QSplitter, model/view classes and Graphics View. 

Proposed shell layout
text
Copy
┌──────────────────────────────────────────────────────────────────────────────┐
│ StableNew   [runtime status] [active model]              [?] [Settings]     │ 48
├───────────────┬──────────────────────────────────────────┬───────────────────┤
│ CREATE        │ Workspace title      contextual toolbar │ Inspector / Queue │
│  Prompt       ├──────────────────────────────────────────┤                   │
│  Pipeline     │                                          │ Preview           │
│               │                                          │ Effective Settings│
│ EDIT          │              Primary workspace           │ Metadata          │
│  Review       │                                          │                   │
│  Photo Opt.   │                                          │ Dockable /        │
│               │                                          │ collapsible       │
│ MOTION        │                                          │                   │
│  Video        │                                          │                   │
│  SVD          │                                          │                   │
│  Movie Clips  │                                          │                   │
│               │                                          │                   │
│ LEARN         │                                          │                   │
│ ADVANCED      │                                          │                   │
├───────────────┴──────────────────────────────────────────┴───────────────────┤
│ Queue: 3   Running: job…   Backend: Ready   [Pause]            status text  │ 28
└──────────────────────────────────────────────────────────────────────────────┘
      ~224 dp                   flexible                         ~320 dp
The right side should be a genuine dockable inspector rather than a fixed third column. A 1366×768 environment can collapse or overlay it; larger screens can retain it. QDockWidget exists specifically for dock/floating desktop tool panels, making this architecture less custom than an equivalent Quick implementation. 

Workspace mock specifications
Create should use an authoring-first layout: navigation on the left, prompt/pipeline work in the center, and a right Preview/Effective Settings/Queue inspector. Model and Profile stay visually adjacent because the existing profile behavior is model-scoped. Preview should show a strong stale-state banner when the accepted draft no longer reflects working settings.

Edit should use a media-workstation layout: source/selection rail on the left, large QGraphicsView canvas in the center, editing/metadata inspector on the right, and a compact persistent action bar along the bottom. The canvas owns no business state; it renders a mask document whose coordinates remain source-image based. Qt Graphics View's explicit scene/view coordinate mapping makes this the lowest-risk implementation for the first mask port. 

Motion should use source assets and shot/sequence organization at left, player in the center, parameters/runtime inspector at right and an optional bottom timeline. The timeline is the best initial QML candidate because Qt Quick's Flickable, ListView, delegates and scene graph suit horizontal retained interaction. 

Learn should visually expose the existing Design → Preview → Run → Compare → Rate sequence as a persistent workflow strip, with experiment configuration/results below and a shared media inspector to the right. That matches current product semantics instead of inventing a new experiment lifecycle.

Component set
Primary implementation components would be QMainWindow, QStackedWidget, QDockWidget, QSplitter, QToolBar, QListView, QTreeView, QTableView, QAbstractListModel, QAbstractTableModel, proxy models, QPlainTextEdit, QCompleter, QGraphicsView, QGraphicsScene, QMediaPlayer, QVideoWidget, QDialog and standard form controls. QML is limited to perhaps a timeline, advanced comparison viewer or future node/workflow surface. 

Engineering lift
Work	Planning estimate
M0 feasibility/runtime proof	2–4 engineer-weeks
M1 toolkit-neutral boundary	3–5
M2 Qt shell/design system	2–4
M3 first real Create workflow	3–5
M4 complete Create + History/Settings	3–5
M5 Motion + Learn	3–5
M6 Edit / precision media	4–6
M7 qualification/cutover	2–4
Full planning range	20–32 engineer-weeks

These ranges assume substantial reuse of existing application services and pure presentation contracts. They are not a schedule commitment and should be recalibrated after M0/M1.

Performance/resource expectation
COA A should have the lower graphics-risk profile because most UI is conventional Widgets and does not require a continuously rendered Qt Quick scene. GPU usage will still occur for video and any accelerated graphics surface, but the shell does not intrinsically require the entire UI to participate in Qt Quick's scene graph. That is an architectural expectation, not a measured StableNew benchmark.

Selective QML should preferably be implemented as a bounded Quick window/surface after measurement. Repeated use of QQuickWidget should be avoided: Qt documents an extra offscreen render pass and disabled threaded render loop for QQuickWidget, potentially increasing GPU fragment load. 

Licensing and packaging
PySide6/Qt for Python supports LGPLv3/GPLv3 or commercial licensing. An LGPL distribution can be feasible, but Qt explicitly requires compliance including notices/source availability and user rights around library replacement/relinking, and notes that some Qt modules are GPL-only for open-source use. This is a licensing-review gate, not merely an engineering decision. 

For deployment, pyside6-deploy uses Nuitka and, as of 6.12, defaults to standalone mode. It can explicitly exclude heavy QML plugins, and Qt warns that indiscriminate QML plugin inclusion can pull in large modules such as QtWebEngine even when not intentionally used. COA A should therefore avoid QtWebEngine unless a concrete requirement arises. 

Principal risks
The dominant risk is not Qt itself; it is incomplete architectural separation. Current composition and some controller behavior still know about MainWindowV2 and Tk-specific invocation.

The second risk is false parity: a new interface can look correct while subtly changing Preview invalidation, queue admission, settings source semantics, mask coordinates or media disposal. Side-by-side deterministic behavioral tests matter more than screenshot similarity.

The third risk is uncontrolled hybridization. A Widgets application containing many independent QQuickWidgets could inherit complexity from both frameworks without capturing the advantages of either. Qt's documented QQuickWidget rendering trade-offs make a strict rule appropriate: each QML surface requires a concrete UX reason and measured resource test. 

COA B — Qt Quick/QML-first desktop application
COA B retains Python services and PySide6 but uses ApplicationWindow, Qt Quick Controls, SplitView, StackView, ListView, TableView, QML media and custom Quick components for nearly the whole presentation layer. Qt Quick Controls provides standard container controls including SplitView, StackView, ToolBar and table/list components, and Python QAbstractListModel implementations can expose roles directly to QML. 

For a branded interface, I would base the QML control library on the Basic style, not customize the Windows native style. Qt recommends building customized controls on a cross-platform customizable style such as Basic or Fusion rather than modifying native platform styles; Basic is intentionally lightweight and minimizes animations/transitions. 

Proposed shell layout
The visual arrangement can be almost identical to COA A, but everything is a QML component:

text
Copy
ApplicationWindow
 ├─ AppCommandBar
 ├─ Row
 │   ├─ NavigationRail
 │   └─ SplitView
 │       ├─ WorkspaceStack
 │       │   ├─ CreatePage
 │       │   ├─ EditPage
 │       │   ├─ MotionPage
 │       │   └─ LearnPage
 │       └─ InspectorPane
 └─ RuntimeStatusBar
The primary UX advantage is that animated pane changes, timeline interaction, media overlays and custom transitions become natural first-class surfaces. Qt Quick's scene graph can render on a dedicated render thread on supported configurations, while the GUI thread prepares subsequent state. 

The drawback is that StableNew is predominantly a dense desktop engineering application, not a motion-first consumer UI. Many of its strongest needs—complex tables, settings, prompt editing, desktop docking and precision image manipulation—already map very directly to Widgets. A Quick-first design therefore spends additional engineering effort re-creating desktop behaviors that Widgets supply natively.

Component set
Core QML components would include ApplicationWindow, SplitView, StackView, ListView, GridView, TableView, ScrollView, TextArea, custom tokenized Controls, Flickable, Image, Canvas or custom QQuickItem for editing, MediaPlayer, VideoOutput, and Python-backed QAbstractListModel/QAbstractTableModel objects. 

The same Python command/projection boundary should still be used. QML should consume intentionally exposed models/properties and emit domain-level commands; it should not receive a raw AppController object with dozens of callable methods.

Engineering lift
Work	Planning estimate
M0 Quick viability/performance proof	3–4 engineer-weeks
M1 toolkit-neutral boundary	3–5
M2 QML design system/shell	4–6
M3 Create	4–6
M4 Create/History/Settings completion	4–6
M5 Motion/Learn	4–6
M6 Edit/custom precision surfaces	4–7
M7 qualification/cutover	2–4
Full planning range	28–42 engineer-weeks

The largest uncertainty is Edit. A Quick implementation can certainly provide a zoomable image/mask surface, but StableNew would have to establish the same source-pixel coordinate guarantees already required by Review's mask document and viewport contract.

Performance/resource expectation
A full Quick application avoids the specific QQuickWidget penalty and can use Qt Quick's normal scene-graph render loop. On Windows, Qt commonly uses a threaded renderer and hardware rendering, which can produce highly responsive animated surfaces. 

For StableNew, however, that means the GUI becomes an active graphics consumer alongside image/video generation workloads. It is therefore essential to measure idle and active GUI GPU memory, render-thread activity, video playback, generation contention and window-hidden behavior on the actual target GPU. Qt's performance documentation also recommends avoiding event-loop hacks such as manual processEvents() calls and keeping expensive work out of GUI-bound code. 

Licensing and packaging
Licensing remains the same Qt/PySide6 decision as COA A. Packaging becomes somewhat more sensitive because QML modules and plugins must be discovered and bundled correctly; Qt's deployment tool explicitly tracks QML files and can exclude unused heavy modules. 

Principal risks
The first risk is a larger custom-control and desktop-behavior surface. The second is GPU/resource contention. The third is QML/Python boundary sprawl if every Python service is exposed directly rather than behind focused presentation models. The fourth is a larger accessibility qualification burden for custom QML components, even though Qt Quick supplies accessibility metadata mechanisms. 

Framework trade-off comparison
Criterion	Current Tk	COA A Widgets + selective QML	COA B Quick-first	Tauri + React hybrid
Existing Python reuse	Excellent	Excellent	Excellent	Moderate
Desktop forms/settings	Moderate	Excellent	Good	Good
Large tables/model-view	Moderate	Excellent	Good	Excellent web ecosystem
Precision image canvas	Moderate/current custom	Excellent fit via Graphics View	Good, more custom	Canvas/WebGL custom
Dockable desktop UI	Weak/custom	Excellent	Custom	Custom/web layout
Timeline/animation	Weak	Very good selectively	Excellent	Excellent
Accessibility foundation	Weak in current Tk implementation	Strong	Strong if custom controls annotated	Strong potential, browser-dependent
High-DPI foundation	Current app has known Tk limitation	Strong Qt 6 support	Strong Qt 6 support	WebView-dependent
New languages/toolchains	None	QML only where used	QML throughout	Rust + JS/TS + Python
IPC boundary	None	None required	None required	Required between web/Rust/Python
GPU exposure	Low	Low–moderate	Moderate–high	Moderate
Migration risk	None	Medium-high	High	Very high
Figma-to-implementation fidelity	Moderate	High	Very high	Very high
Packaging complexity	Existing	Medium	Medium-high	High
Recommendation	Maintain during transition	Preferred	Alternative	Not preferred

Tauri is credible technology but is a weaker architectural fit here. Tauri uses a web frontend rendered through the system WebView and a message-passing architecture; on Windows its distribution also has to account for WebView2 and installer strategy. That would introduce Rust/JavaScript and an IPC/service boundary to an application whose core services are already Python. 

For a new product designed from the outset as a local/web hybrid, that trade could be attractive. For StableNew, it increases migration scope without solving a problem that Qt cannot already solve in-process.

Decision: COA A wins because it gives StableNew the desktop capabilities it actually needs while minimizing architectural novelty. COA B is technically viable and should remain the design ceiling for isolated media/timeline surfaces, not the default application host.

Architecture and implementation patterns
Presentation boundary
The target code organization should make toolkit selection a composition-root concern:

text
Copy
src/
  app/
    presentation/
      commands.py
      projections.py
      subscriptions.py
      dispatcher.py

  gui_v2/
    adapters/
    validation/
    ...existing pure projections...

  gui/
    ...existing Tk host during migration...

  gui_qt/
    app.py
    shell/
    models/
    views/
    widgets/
    qml/
    bridges/
    theme/

  controller/
  queue/
  pipeline/
  generation_profiles/
  learning/
  video/
This is a target proposal, not a description of current repository directories. Current authority still states that src/gui/ is the active Tk host and src/gui_v2/ is toolkit-independent scaffolding rather than a second GUI.

The most important M1 design constraint is that controllers never receive a Qt widget as their application API. AppController.set_main_window(window) is the dependency that should ultimately disappear behind narrower ports. Current source demonstrates that AppController still uses main_window for some GUI dispatch and root ownership, so this is an evidence-based migration target, not theoretical architecture cleanup.

Model/view binding pattern
A Python QAbstractListModel can serve both QListView and QML ListView. Qt explicitly supports this shared model/view design. 

A model-browser adapter could look like this:

python
Copy
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt


@dataclass(frozen=True)
class ModelRow:
    model_id: str
    name: str
    family: str
    status: str


class ModelListModel(QAbstractListModel):
    ModelIdRole = int(Qt.ItemDataRole.UserRole) + 1
    NameRole = ModelIdRole + 1
    FamilyRole = NameRole + 1
    StatusRole = FamilyRole + 1

    def __init__(self, rows: list[ModelRow] | None = None, parent=None) -> None:
        super().__init__(parent)
        self._rows = list(rows or [])

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None

        row = self._rows[index.row()]

        if role in (Qt.ItemDataRole.DisplayRole, self.NameRole):
            return row.name
        if role == self.ModelIdRole:
            return row.model_id
        if role == self.FamilyRole:
            return row.family
        if role == self.StatusRole:
            return row.status
        return None

    def roleNames(self) -> dict[int, bytes]:
        return {
            self.ModelIdRole: b"modelId",
            self.NameRole: b"name",
            self.FamilyRole: b"family",
            self.StatusRole: b"status",
        }

    def replace_rows(self, rows: list[ModelRow]) -> None:
        self.beginResetModel()
        self._rows = list(rows)
        self.endResetModel()
The model should contain presentation rows copied from the actual model-inventory projection, not scan the filesystem or own model selection itself. That keeps it aligned with StableNew's existing rule that presentation models do not become subsystem authorities.

A QML list can consume the same roles:

qml
Copy
import QtQuick
import QtQuick.Controls.Basic

ListView {
    id: modelList
    model: modelListModel
    clip: true
    spacing: 4

    delegate: ItemDelegate {
        required property string modelId
        required property string name
        required property string family
        required property string status

        width: ListView.view.width
        text: name

        Accessible.name: name + ", " + family + ", " + status

        onClicked: {
            modelCommands.selectModel(modelId)
        }
    }
}
Qt Quick accessibility metadata is explicitly supported through its Accessible API, but any custom delegate still needs appropriate semantic testing. 

Image canvas with overlays
For COA A's production mask editor, I recommend QGraphicsView rather than QML because its scene/item/view coordinate mapping directly matches the core risk. 

A QML image/overlay surface remains useful for media inspection or lightweight annotation:

qml
Copy
import QtQuick
import QtQuick.Controls.Basic

Flickable {
    id: viewport

    property real zoom: 1.0
    property var overlays: []

    clip: true
    contentWidth: image.implicitWidth * zoom
    contentHeight: image.implicitHeight * zoom

    Item {
        width: image.implicitWidth * viewport.zoom
        height: image.implicitHeight * viewport.zoom

        Image {
            id: image
            anchors.fill: parent
            source: canvasSource
            fillMode: Image.PreserveAspectFit
            smooth: true
        }

        Repeater {
            model: viewport.overlays

            Rectangle {
                required property var modelData

                x: modelData.x * viewport.zoom
                y: modelData.y * viewport.zoom
                width: modelData.width * viewport.zoom
                height: modelData.height * viewport.zoom

                color: "transparent"
                border.width: 2
                border.color: "#FFC805"
            }
        }
    }

    ScrollBar.horizontal: ScrollBar {}
    ScrollBar.vertical: ScrollBar {}
}
The important architectural property is that overlay geometry remains in source-space coordinates and the view derives screen placement from the current zoom. That same principle should govern a QGraphicsScene implementation.

GUI-thread dispatch
Qt requires GUI objects to remain on the GUI thread, while queued signals can deliver results across threads. Qt's threading documentation describes QObject thread affinity and cross-thread signal/event delivery; it should replace root.after() rather than be layered around it. 

A Qt implementation of StableNew's existing UiDispatcher contract can be small:

python
Copy
from collections.abc import Callable

from PySide6.QtCore import QObject, Qt, Signal, Slot


class QtUiDispatcher(QObject):
    _invoke_requested = Signal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._invoke_requested.connect(
            self._run,
            Qt.ConnectionType.QueuedConnection,
        )

    def invoke(self, fn: Callable[[], None]) -> None:
        self._invoke_requested.emit(fn)

    @Slot(object)
    def _run(self, fn: Callable[[], None]) -> None:
        fn()
This adapter should be created on the GUI thread and injected where the current UiDispatcher abstraction is already accepted. The existing protocol makes this a natural extraction.

Worker/thread pattern with latest-request-wins
Qt's recommended QObject/QThread architecture maps cleanly to StableNew's existing requirement that filesystem/media work happen in background services and that stale results be discarded. 

python
Copy
from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot


class PreviewWorker(QObject):
    result = Signal(int, object)
    failed = Signal(int, str)
    finished = Signal()

    def __init__(self, revision: int, request: object) -> None:
        super().__init__()
        self.revision = revision
        self.request = request

    @Slot()
    def run(self) -> None:
        try:
            # Pure/background work only.
            value = build_preview_projection(self.request)
            self.result.emit(self.revision, value)
        except Exception as exc:
            self.failed.emit(self.revision, str(exc))
        finally:
            self.finished.emit()


class PreviewCoordinator(QObject):
    def __init__(self) -> None:
        super().__init__()
        self._revision = 0
        self._threads: set[QThread] = set()

    def request(self, request: object) -> None:
        self._revision += 1
        revision = self._revision

        thread = QThread(self)
        worker = PreviewWorker(revision, request)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.result.connect(
            self._accept_if_current,
            Qt.ConnectionType.QueuedConnection,
        )
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._threads.discard(thread))

        self._threads.add(thread)
        thread.start()

    @Slot(int, object)
    def _accept_if_current(self, revision: int, value: object) -> None:
        if revision != self._revision:
            return
        self.apply_projection(value)

    def apply_projection(self, value: object) -> None:
        ...
Production StableNew should preferably reuse its existing background coordinators rather than manufacture one QThread per lookup; the example illustrates the thread-affinity and stale-revision pattern, not a required replacement of current worker infrastructure.

Prompt editor pattern
For Prompt, a QPlainTextEdit-based editor is preferable to building a code-editor-like QML surface from scratch. QSyntaxHighlighter can visually distinguish prompt constructs without mutating prompt data, while QCompleter can provide LoRA/model/embedding suggestions from an explicit model. 

The acceptance principle is important: highlighting and completion are presentation aids only. They must not rewrite the PromptPack or perform model-aware adaptation without the existing explicit command path.

Migration roadmap and acceptance gates
The earlier M0→M7 structure remains sound, but the new research clarifies what each phase must prove and when rollback remains inexpensive.

yes

no

yes

no

yes

no

M0
Feasibility

GO?

M1
Decoupling

Continue Tk modernization

M2
Foundation

M3
First workflow

Create parity?

M4
Create + History

Keep Tk default
repair boundary

M5
Motion + Learn

M6
Editing

Full parity
and resource gates?

M7
Cutover

Qt remains optional
Tk production host



Show code
Milestone plan
Phase	Milestone	Measurable acceptance tests	Rollback criterion
M0 — Feasibility	Prove PySide6 6.12/Python 3.14, Windows deployment, dispatcher, model/view, one media and one QML experiment	Clean isolated launch/close; packaged smoke run; 100/150% DPI screenshots; queued worker delivery; licensing module inventory; idle/startup/RAM/GPU measurements	Any blocking packaging/license/lifecycle issue, or unacceptable resource profile
M1 — Decoupling	Qt and Tk can consume a common presentation boundary	Existing Tk test suite remains green; selected controller paths no longer require widget/root refs; UiDispatcher injectable; AppState scheduling no longer hard-wired to Tk	Tk regression or need to duplicate queue/state authority
M2 — Foundation	Qt shell, tokens, navigation, settings skeleton, accessibility baseline	All stable tab IDs resolve; old persisted selected_tab_id and legacy index behavior pass; 1366×768/1920×1080 at 100/150%; keyboard traversal; destroy/reopen stress	Navigation/persistence cannot coexist with current format
M3 — First workflow	Model/profile selection → Preview → queue in Qt	Same inputs yield structurally identical accepted Preview/NJRs; model profile application parity; stale-preview behavior identical; fake/controlled queue submission exactly once	Any execution-semantic divergence
M4 — Create + History	Prompt, Pipeline, history and settings are production-capable	PromptPack round-trip; Preview/Run/Add-to-Queue parity; paged history/search; replay/resume lineage; settings persistence; no shadow queue/history	Durable-state mismatch or replay/settings incompatibility
M5 — Motion + Learn	Video, SVD, Movie Clips and Learning migrated	Playback disposal; repeated source switching without stale frames; sequence ordering/submission parity; Design→Preview→Run→Compare→Rate behavior and persistence	Decoder/process leaks, sequence semantic mismatch, Learning evidence loss
M6 — Editing	Review and Photo Optimize reach parity	Golden mask-coordinate suite at zoom/DPI combinations; mask pixel output parity; undo/redo; outpaint/reprocess admission; independent Original/Candidate state	Any pixel-coordinate or artifact-lineage discrepancy
M7 — Cutover	Qt becomes default after qualification	Full parity matrix; Windows installer; startup/shutdown soak; screen-reader/UIA pass; DPI/multi-monitor pass; resource regression budget; operator acceptance	Any P0/P1 regression; switch default back to Tk

M0 measurements that should be mandatory
Because no runtime tests were executed for this report, M0 should establish real baselines before further architectural commitment. At minimum it should measure cold/warm startup, idle process working set, GUI-only GPU memory, idle GPU utilization, resize latency, first large-history render, a 5,000-row model/table projection, image zoom/pan, video playback, QML timeline animation, hide/show resource release, shutdown latency and package/install size on the intended Windows system.

Do not set arbitrary pass/fail numbers before measuring the current Tk baseline. The meaningful acceptance criterion is regression against existing behavior plus operator responsiveness. For example, a Qt UI that adds a modest amount of RAM but eliminates synchronous UI stalls may be a positive trade; a QML timeline that consumes material VRAM while a generation job is active may not be.

Packaging gate
PySide6 6.12 currently supplies Windows x86-64 wheels and Python 3.14 classification, making dependency compatibility plausible. The package itself is only a metapackage; actual Qt modules and plugins materially affect deployed size, so installer-size estimates should come from the actual M0 deployment rather than PyPI's small top-level wheel. 

pyside6-deploy should be tested in a disposable, controlled build environment. Qt documents that the tool installs deployment dependencies unless --no-install is used, and that Nuitka follows imports in a way that executes module-level project code during building. StableNew's build pipeline should therefore use a clean, trusted build environment and treat pysidedeploy.spec as controlled source. 

Rollback architecture
Tk should remain the production host through at least M4. The Qt host should be a separate composition root using the same services and persistent stores, never a second in-process Tk/Qt dual-loop application. A cutover should mean changing which shell is started, not migrating application data.

The safest retirement rule is: do not delete the Tk host until Qt has passed all P0/P1 parity gates, qualified packaging and shutdown, and completed an operator acceptance period. Until that point, rollback should consist of selecting the Tk composition root with the same settings/database—not restoring a backup database or converting user files.

Decision and Figma handoff
Recommended course
Proceed with COA A.

The strongest argument is architectural rather than cosmetic. StableNew already has a Python service architecture, toolkit-neutral contracts and a durable SQLite execution/history authority. PySide6 lets the application keep those assets in-process while gaining the desktop capabilities StableNew is increasingly asking Tk to emulate: robust model/view tables, dockable panels, advanced 2D scene coordinates, stronger high-DPI behavior, media integration and a real accessibility framework. 

Qt Quick should be treated as a specialized rendering technology inside the Qt architecture, not the default answer for every new screen. A timeline or sophisticated media compare surface can justify QML. A settings dialog, history table, model list or prompt editor generally does not.

The largest precondition is M1-style separation. build_v2_app() still owns Tk composition, AppState still has a Tk-specific invoker dependency, and AppController retains some direct window usage. Those are manageable seams, but they must be resolved before substantial Qt view development or the migration will create a second layer of GUI coupling instead of removing the first.

Decision matrix
Decision factor	COA A	COA B
Preserve Python architecture	Strong	Strong
Match StableNew's dense desktop workflows	Strongest	Moderate-strong
Precision Edit implementation	Strongest	Higher custom risk
Motion/timeline UX ceiling	Strong	Strongest
Figma fidelity	Strong	Strongest
GPU/resource conservatism	Stronger	Weaker until measured
Native docking/tool layout	Strongest	Custom
Migration complexity	Lower	Higher
Accessibility effort	Lower for standard controls	Higher for custom controls
Deployment complexity	Moderate	Moderate-high
Overall recommendation	GO	Reserve as alternative

Figma visual mock set
The design team should produce—not as part of this report—the following Figma-ready SVG/component specification package before M2 implementation:

Frame / artifact	Required visual content
Global shell	Navigation groups, runtime status, queue state, inspector dock, settings entry
Create / Prompt	Prompt editor, negative prompt, PromptPack context, model target compatibility, LoRA/model affordances
Create / Pipeline	Model + profile row, generation composer, Preview, Effective Settings, queue action
History	Filter/search, virtualized table, status chips, selected-job inspector, media preview, replay/regenerate actions
Edit / Review	Large canvas, asset selection, mask toolbar, before/after state, reprocess controls
Edit / Photo Optimize	Original/Candidate split, independent media controls, optimization settings
Motion	Player, source rail, runtime/preflight state, shot settings, bottom timeline
Learn	Design/Preview/Run/Compare/Rate workflow, experiment matrix, result inspector
Settings	Vertical category navigation, form panels, restart-required state, runtime ownership messaging
States sheet	Loading, empty, unavailable, disconnected, error, warning, HOLD, content-hidden, no-media
Component library	Every state/variant defined earlier, with keyboard and accessibility annotations
Icon sheet	16/20/24 SVG masters, naming convention, stroke/padding rules
Responsive sheet	1366×768, 1440×900 and 1920×1080; right-dock open/collapsed; 100%/150% annotations

The Figma package should also include a component-spec page intended for implementation rather than presentation: exact semantic token names, auto-layout rules, min/max widths, wrapping behavior, component state machines, focus order, keyboard shortcuts, accessibility names, empty/loading/error behavior and corresponding Qt component target. That prevents the design from becoming a collection of static screenshots that cannot be faithfully implemented.

Immediate M0 decision tests
Before authorizing M1, the M0 package should reduce four remaining uncertainties:

First, architecture: prove that a Qt application can consume a mock/real-safe StableNew projection through a QtUiDispatcher, dispose its subscriptions cleanly and close without Tk. The existing UiDispatcher protocol gives this experiment a natural boundary.

Second, packaging: create an isolated Windows PySide6 6.12 package with only the likely modules—Core, Gui, Widgets, Multimedia and the minimum Quick/QML modules for one experiment—and record deployed files, license inventory, startup and installer footprint. Qt's deployment tooling supports module/plugin control, so this can be measured rather than guessed. 

Third, graphics resources: benchmark a Widgets-only shell against one Quick-first shell and one selective-QML timeline while an actual representative StableNew GPU workload is running. This is particularly important because QQuickWidget has documented rendering costs, while a normal Qt Quick window can use a dedicated scene-graph render thread. 

Fourth, licensing: enumerate exactly which Qt modules the production design requires and obtain an explicit distribution decision—LGPL-compliant dynamic distribution or commercial licensing—before M2 hardens packaging. Qt itself recommends legal review for detailed LGPL suitability and notes that some framework components have different open-source terms. 

Decision-grade conclusion: StableNew has enough toolkit-neutral architecture already in place that a controlled Qt migration is credible, and its current workflow complexity is now high enough that a stronger desktop framework offers meaningful engineering value beyond appearance. The optimal path is not “rewrite the GUI in QML.” It is finish the presentation boundary, make Qt Widgets the durable desktop foundation, and use QML only where the interaction model demonstrably benefits from it.