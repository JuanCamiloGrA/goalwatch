import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "com.goalwatch"
  ipcTarget: "com.goalwatch"

  readonly property string runtimeDir: Quickshell.env("XDG_RUNTIME_DIR") || ""
  readonly property string statePath: runtimeDir + "/goalwatch/state.json"
  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property color watchBlue: "#3A8DFF"
  readonly property color alertRed: "#FF4D4F"
  readonly property color cardColor: Qt.rgba(foreground.r, foreground.g, foreground.b, 0.045)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  property var snapshot: ({})
  property var metrics: ({})
  property string saveError: ""
  property string integrationNotice: ""
  property bool alertActive: false
  property bool effectiveActive: false
  property bool effectiveObsidian: false
  property bool syncingFields: false
  property bool manualSaveQueued: false
  property int pendingObsidianAction: 0
  property bool auditMode: false
  property var auditRecords: []
  property var selectedAudit: ({})
  property int auditTotal: 0
  property int auditOffset: 0
  property int auditLimit: 50
  property string auditOutcome: "all"
  property string auditError: ""
  property bool auditQueryQueued: false
  property bool clearAuditArmed: false
  property int pendingAuditId: 0
  readonly property double nowMs: liveClock.date.getTime()
  readonly property string statusText: snapshot.state === undefined ? "OFF" : bounded(snapshot.state, 40)
  readonly property color eyeColor: alertActive ? alertRed : (effectiveActive ? watchBlue : dim)

  function parseState(content) {
    try {
      var parsed = JSON.parse(String(content || "{}"))
      snapshot = parsed && typeof parsed === "object" ? parsed : ({})
      metrics = parsed && parsed.metrics && typeof parsed.metrics === "object" ? parsed.metrics : ({})
      alertActive = parsed && parsed.alert && parsed.alert.active === true
      effectiveActive = parsed && parsed.active === true
      effectiveObsidian = parsed && parsed.obsidian_enabled === true
      syncFields()
    } catch (e) {
      console.warn("GoalWatch: ignoring invalid runtime state", e)
    }
  }

  function bounded(value, limit) {
    return String(value === undefined || value === null ? "" : value).slice(0, limit)
  }

  function syncFields() {
    syncingFields = true
    if (intervalField && !intervalField.activeFocus)
      intervalField.text = String(snapshot.interval_minutes || 5)
    if (modelField && !modelField.activeFocus)
      modelField.text = bounded(snapshot.model || "gemini-flash-lite-latest", 160)
    if (pathField && !pathField.activeFocus)
      pathField.text = bounded(snapshot.markdown_file || "", 4096)
    if (goalField && !goalField.activeFocus)
      goalField.text = bounded(snapshot.manual_goal || "", 2000)
    if (toolsField && !toolsField.activeFocus)
      toolsField.text = bounded(snapshot.manual_tools || "Codex, Browser, Obsidian and any tool useful to the goal.", 3000)
    syncingFields = false
  }

  function toggleWatching() {
    if (toggleProc.running) return
    effectiveActive = !effectiveActive
    toggleProc.running = true
  }

  function saveManualGoal() {
    if (syncingFields || effectiveObsidian) return
    if (manualGoalProc.running) {
      manualSaveQueued = true
      return
    }
    var goal = String(goalField.text || "").trim()
    var tools = String(toolsField.text || "").trim()
    if (goal === String(snapshot.manual_goal || "") && tools === String(snapshot.manual_tools || "")) {
      manualSaveQueued = false
      if (pendingObsidianAction !== 0) {
        var unchangedAction = pendingObsidianAction
        pendingObsidianAction = 0
        startObsidian(unchangedAction > 0)
      }
      return
    }
    if (goal.length > 2000 || tools.length > 3000) {
      saveError = "Current Goal or Available Tools is too long."
      pendingObsidianAction = 0
      return
    }
    saveError = ""
    integrationNotice = ""
    manualSaveQueued = false
    manualGoalProc.payload = JSON.stringify({"goal": goal, "tools": tools})
    manualGoalProc.running = true
  }

  function toggleObsidian() {
    runObsidian(!effectiveObsidian)
  }

  function runObsidian(enable) {
    if (obsidianProc.running) return
    if (enable) {
      saveManualGoalTimer.stop()
      pendingObsidianAction = 1
      saveManualGoal()
      if (manualGoalProc.running || pendingObsidianAction === 0) return
    }
    startObsidian(enable)
  }

  function startObsidian(enable) {
    if (obsidianProc.running) return
    effectiveObsidian = enable
    saveError = ""
    integrationNotice = enable ? "Connecting to Obsidian…" : "Disconnecting from Obsidian…"
    obsidianProc.enabling = enable
    obsidianProc.responseSeen = false
    obsidianProc.command = ["goalwatch", "obsidian", enable ? "enable" : "disable"]
    obsidianProc.running = true
  }

  function handleObsidianResponse(content) {
    try {
      var response = JSON.parse(String(content || "{}"))
      obsidianProc.responseSeen = true
      if (response.ok === true) {
        saveError = ""
        integrationNotice = String(response.message || "Obsidian Sync updated.")
        if (Array.isArray(response.warnings) && response.warnings.length > 0)
          integrationNotice += " " + String(response.warnings[0])
      } else {
        effectiveObsidian = snapshot.obsidian_enabled === true
        integrationNotice = ""
        saveError = String(response.error || "Could not update Obsidian Sync.")
      }
    } catch (e) {
      console.warn("GoalWatch: could not parse Obsidian response", e)
    }
  }

  function saveInterval() {
    var value = String(intervalField.text || "").trim()
    if (intervalProc.running || value === String(snapshot.interval_minutes || 5)) return
    var parsed = parseInt(value, 10)
    if (!isFinite(parsed) || parsed < 1 || parsed > 1440) {
      saveError = "Interval must be between 1 and 1440 minutes."
      return
    }
    saveError = ""
    intervalProc.command = ["goalwatch", "config", "set", "interval_minutes", String(parsed)]
    intervalProc.running = true
  }

  function saveModel() {
    var value = String(modelField.text || "").trim()
    if (modelProc.running || value === String(snapshot.model || "")) return
    if (value === "" || /\s/.test(value)) {
      saveError = "Model must be a valid Gemini model identifier."
      return
    }
    saveError = ""
    modelProc.command = ["goalwatch", "config", "set", "model", value]
    modelProc.running = true
  }

  function savePath() {
    var value = String(pathField.text || "").trim()
    if (pathProc.running || value === String(snapshot.markdown_file || "")) return
    if (value !== "" && !value.toLowerCase().endsWith(".md")) {
      saveError = "Markdown File must end in .md."
      return
    }
    saveError = ""
    pathProc.command = ["goalwatch", "config", "set", "markdown_file", value]
    pathProc.running = true
  }

  function saveApiKey() {
    var value = String(apiKeyField.text || "").trim()
    if (apiKeyProc.running || value === "") return
    saveError = ""
    apiKeyProc.secret = value
    apiKeyProc.running = true
  }

  function humanDuration(seconds) {
    var value = Math.floor(Math.max(0, Number(seconds || 0)))
    if (value < 60) return value + "s"
    var minutes = Math.floor(value / 60)
    if (minutes < 60) return minutes + "m " + (value % 60) + "s"
    return Math.floor(minutes / 60) + "h " + (minutes % 60) + "m"
  }

  function since(iso, currentTimeMs) {
    if (!iso) return "—"
    var timestamp = Date.parse(String(iso))
    if (!isFinite(timestamp)) return "—"
    return humanDuration(Math.floor((currentTimeMs - timestamp) / 1000))
  }

  function until(iso, currentTimeMs) {
    if (!iso) return "—"
    var timestamp = Date.parse(String(iso))
    if (!isFinite(timestamp)) return "—"
    return humanDuration(Math.max(0, Math.ceil((timestamp - currentTimeMs) / 1000)))
  }

  function refreshState() { stateFile.reload() }

  function openAudit() {
    auditMode = true
    auditOffset = 0
    auditError = ""
    clearAuditArmed = false
    queryAudit()
  }

  function closeAudit() {
    auditMode = false
    clearAuditArmed = false
    auditSearchField.text = ""
    auditOutcome = "all"
    selectedAudit = ({})
  }

  function queryAudit() {
    if (auditQueryProc.running) {
      auditQueryQueued = true
      return
    }
    auditError = ""
    auditQueryQueued = false
    auditQueryProc.payload = JSON.stringify({
      "outcome": auditOutcome,
      "query": String(auditSearchField.text || "").slice(0, 200),
      "limit": auditLimit,
      "offset": auditOffset
    })
    auditQueryProc.running = true
  }

  function handleAuditQuery(content) {
    try {
      var response = JSON.parse(String(content || "{}"))
      auditRecords = Array.isArray(response.records) ? response.records : []
      auditTotal = Number(response.total || 0)
      auditOffset = Number(response.offset || 0)
      if (auditRecords.length > 0)
        loadAudit(Number(auditRecords[0].id))
      else
        selectedAudit = ({})
    } catch (e) {
      auditError = "Could not read the audit index."
    }
  }

  function loadAudit(recordId) {
    if (!isFinite(recordId)) return
    if (auditDetailProc.running) {
      pendingAuditId = Math.floor(recordId)
      return
    }
    pendingAuditId = 0
    auditError = ""
    auditDetailProc.command = ["goalwatch", "audit", "show", String(Math.floor(recordId))]
    auditDetailProc.running = true
  }

  function handleAuditDetail(content) {
    try {
      var response = JSON.parse(String(content || "{}"))
      selectedAudit = response && typeof response === "object" ? response : ({})
    } catch (e) {
      auditError = "Could not read that audit record."
    }
  }

  function auditOutcomeLabel(value) {
    if (value === "on_goal") return "ON GOAL"
    if (value === "off_goal") return "OFF GOAL"
    if (value === "pending") return "PENDING"
    return "ERROR"
  }

  function auditOutcomeColor(value) {
    if (value === "on_goal") return root.watchBlue
    if (value === "off_goal") return root.alertRed
    if (value === "pending") return root.dim
    return "#F2B84B"
  }

  function auditTime(value) {
    var date = new Date(String(value || ""))
    return isNaN(date.getTime()) ? "Unknown time" : date.toLocaleString(Qt.locale(), "yyyy-MM-dd  HH:mm:ss")
  }

  function auditImageUrl(value) {
    var path = String(value || "")
    return path === "" ? "" : "file://" + encodeURI(path)
  }

  function clearAudit() {
    if (auditClearProc.running) return
    if (!clearAuditArmed) {
      clearAuditArmed = true
      clearAuditArmTimer.restart()
      return
    }
    clearAuditArmed = false
    auditClearProc.running = true
  }

  IpcHandler {
    target: "com.goalwatch.audit"
    function open(): void {
      root.openAudit()
      root.open()
    }
  }

  onOpenedChanged: if (opened) {
    refreshState()
    syncFields()
    Qt.callLater(function() { keyCatcher.forceActiveFocus() })
  }

  FileView {
    id: stateFile
    path: root.statePath
    watchChanges: true
    printErrors: false
    onLoaded: root.parseState(text())
    onFileChanged: reload()
  }

  Process {
    id: toggleProc
    command: ["goalwatch", "toggle"]
    onExited: function(exitCode) {
      if (exitCode !== 0) {
        root.effectiveActive = root.snapshot.active === true
        root.saveError = "Could not toggle GoalWatch."
      }
      settleTimer.restart()
    }
  }

  Process {
    id: auditQueryProc
    property string payload: ""
    property bool responseSeen: false
    command: ["goalwatch", "audit", "query"]
    stdinEnabled: true
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        auditQueryProc.responseSeen = true
        root.handleAuditQuery(text)
      }
    }
    onStarted: write(payload + "\n")
    onExited: function(exitCode) {
      payload = ""
      if (exitCode !== 0 && !responseSeen) root.auditError = "Could not query the audit archive."
      responseSeen = false
      if (root.auditQueryQueued) Qt.callLater(root.queryAudit)
    }
  }

  Process {
    id: auditDetailProc
    property bool responseSeen: false
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        auditDetailProc.responseSeen = true
        root.handleAuditDetail(text)
      }
    }
    onExited: function(exitCode) {
      if (exitCode !== 0 && !responseSeen) root.auditError = "Could not load the audit record."
      responseSeen = false
      if (root.pendingAuditId > 0) {
        var nextId = root.pendingAuditId
        root.pendingAuditId = 0
        Qt.callLater(function() { root.loadAudit(nextId) })
      }
    }
  }

  Process {
    id: auditClearProc
    command: ["goalwatch", "audit", "clear"]
    stdinEnabled: true
    onStarted: write("CLEAR\n")
    onExited: function(exitCode) {
      if (exitCode === 0) {
        root.auditOffset = 0
        root.selectedAudit = ({})
        root.queryAudit()
      } else {
        root.auditError = "Could not clear the audit archive."
      }
    }
  }

  Process {
    id: manualGoalProc
    property string payload: ""
    command: ["goalwatch", "config", "set-manual-goal"]
    stdinEnabled: true
    onStarted: write(payload + "\n")
    onExited: function(exitCode) {
      if (exitCode !== 0) {
        root.saveError = "Could not save the manual goal."
        root.pendingObsidianAction = 0
      } else if (root.manualSaveQueued) {
        saveManualGoalTimer.restart()
      } else if (root.pendingObsidianAction !== 0) {
        var action = root.pendingObsidianAction
        root.pendingObsidianAction = 0
        Qt.callLater(function() { root.startObsidian(action > 0) })
      }
      payload = ""
      settleTimer.restart()
    }
  }

  Process {
    id: obsidianProc
    property bool enabling: false
    property bool responseSeen: false
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.handleObsidianResponse(text)
    }
    onExited: function(exitCode) {
      if (exitCode !== 0 && !responseSeen) {
        root.effectiveObsidian = root.snapshot.obsidian_enabled === true
        root.integrationNotice = ""
        root.saveError = enabling
          ? "Could not connect Obsidian. Manual goals are still available."
          : "Could not disconnect Obsidian."
      }
      settleTimer.restart()
    }
  }

  Process {
    id: intervalProc
    onExited: function(exitCode) {
      if (exitCode !== 0) root.saveError = "Could not save the interval."
      settleTimer.restart()
    }
  }

  Process {
    id: modelProc
    onExited: function(exitCode) {
      if (exitCode !== 0) root.saveError = "Could not save the model."
      settleTimer.restart()
    }
  }

  Process {
    id: pathProc
    onExited: function(exitCode) {
      if (exitCode !== 0) root.saveError = "Could not save the Markdown file."
      settleTimer.restart()
    }
  }

  Process {
    id: apiKeyProc
    property string secret: ""
    command: ["goalwatch", "config", "set-api-key"]
    stdinEnabled: true
    onStarted: write(secret + "\n")
    onExited: function(exitCode) {
      if (exitCode === 0) apiKeyField.text = ""
      else root.saveError = "Could not save the API key."
      secret = ""
      settleTimer.restart()
    }
  }

  Timer {
    id: saveManualGoalTimer
    interval: 650
    repeat: false
    onTriggered: root.saveManualGoal()
  }

  Timer {
    id: auditSearchTimer
    interval: 450
    repeat: false
    onTriggered: {
      root.auditOffset = 0
      root.queryAudit()
    }
  }

  Timer {
    id: clearAuditArmTimer
    interval: 5000
    repeat: false
    onTriggered: root.clearAuditArmed = false
  }

  Timer {
    id: settleTimer
    interval: 420
    repeat: false
    onTriggered: root.refreshState()
  }

  SystemClock {
    id: liveClock
    precision: SystemClock.Seconds
  }

  implicitWidth: buttons.implicitWidth
  implicitHeight: buttons.implicitHeight

  Grid {
    id: buttons
    anchors.fill: parent
    columns: root.bar && root.bar.vertical ? 1 : 2

    BarIconButton {
      bar: root.bar
      tooltipText: "GoalWatch · " + root.statusText
      iconComponent: Component {
        EyeIcon {
          anchors.centerIn: parent
          width: Style.space(18)
          height: Style.space(13)
          color: root.eyeColor
          dotColor: root.eyeColor
        }
      }
      onPressed: function(buttonCode) {
        if (buttonCode === Qt.LeftButton || buttonCode === Qt.RightButton) root.toggleWatching()
      }
    }

    BarIconButton {
      id: gearButton
      bar: root.bar
      text: "⚙"
      tooltipText: "GoalWatch settings"
      onPressed: function(buttonCode) {
        if (buttonCode === Qt.LeftButton || buttonCode === Qt.RightButton) root.toggle()
      }
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: gearButton
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(root.auditMode ? 940 : 420))
    contentHeight: panel.fittedContentHeight(
      root.auditMode ? Style.space(720) : content.implicitHeight,
      Style.space(root.auditMode ? 760 : 720)
    )

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: intervalField.activeFocus || modelField.activeFocus || pathField.activeFocus
        || apiKeyField.activeFocus || goalField.activeFocus || toolsField.activeFocus
        || auditSearchField.activeFocus || auditRequestArea.activeFocus || auditResponseArea.activeFocus
      onCloseRequested: {
        if (root.auditMode) root.closeAudit()
        else root.close()
      }
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(t) {
        if (t === "t" || t === "T") root.toggleWatching()
        else if (t === "r" || t === "R") root.refreshState()
      }

      Flickable {
        visible: !root.auditMode
        anchors.fill: parent
        contentWidth: width
        contentHeight: content.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        flickableDirection: Flickable.VerticalFlick
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        Column {
          id: content
          width: parent.width
          spacing: Style.space(12)

          Item {
            width: parent.width
            implicitHeight: Math.max(heroEye.height, heroLabels.implicitHeight, powerSwitch.height)

            EyeIcon {
              id: heroEye
              width: Style.space(46)
              height: Style.space(31)
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
              color: root.eyeColor
              dotColor: root.eyeColor
            }

            Column {
              id: heroLabels
              anchors.left: heroEye.right
              anchors.leftMargin: Style.space(12)
              anchors.right: powerSwitch.left
              anchors.rightMargin: Style.space(12)
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(2)
              Text {
                width: parent.width
                text: "GoalWatch"
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.title
                font.bold: true
                elide: Text.ElideRight
              }
              Text {
                width: parent.width
                text: root.statusText
                textFormat: Text.PlainText
                color: root.alertActive ? root.alertRed : (root.effectiveActive ? root.watchBlue : root.dim)
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                font.bold: true
                font.letterSpacing: 1.2
              }
            }

            ToggleSwitch {
              id: powerSwitch
              width: Style.space(42)
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              checked: root.effectiveActive
              busy: toggleProc.running
              foreground: root.foreground
              onToggled: root.toggleWatching()
            }
          }

          PanelSeparator { width: parent.width; foreground: root.foreground }
          PanelSectionHeader { text: "GOAL SOURCE"; foreground: root.foreground; fontFamily: root.fontFamily }

          Rectangle {
            width: parent.width
            height: sourceContent.implicitHeight + Style.space(20)
            radius: 5
            color: root.cardColor

            RowLayout {
              id: sourceContent
              anchors.left: parent.left
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              anchors.margins: Style.space(10)
              spacing: Style.space(10)

              Column {
                Layout.fillWidth: true
                spacing: Style.space(3)
                Text {
                  text: "OBSIDIAN SYNC"
                  color: root.effectiveObsidian ? root.watchBlue : root.foreground
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  font.bold: true
                  font.letterSpacing: 0.8
                }
                Text {
                  width: parent.width
                  text: root.effectiveObsidian
                    ? root.bounded(root.snapshot.obsidian_message || "Connected to Obsidian.", 600)
                    : "Off · Manual goal is active"
                  textFormat: Text.PlainText
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  wrapMode: Text.WordWrap
                }
              }

              Rectangle {
                visible: root.effectiveObsidian && root.snapshot.obsidian_connected !== true && !obsidianProc.running
                Layout.preferredWidth: repairText.implicitWidth + Style.space(18)
                Layout.preferredHeight: Style.space(28)
                radius: 4
                color: "transparent"
                border.width: 1
                border.color: root.watchBlue
                Text {
                  id: repairText
                  anchors.centerIn: parent
                  text: "REPAIR"
                  color: root.watchBlue
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  font.bold: true
                }
                MouseArea {
                  anchors.fill: parent
                  cursorShape: Qt.PointingHandCursor
                  onClicked: root.runObsidian(true)
                }
              }

              ToggleSwitch {
                Layout.preferredWidth: Style.space(42)
                checked: root.effectiveObsidian
                busy: obsidianProc.running
                foreground: root.foreground
                onToggled: root.toggleObsidian()
              }
            }
          }

          Column {
            visible: !root.effectiveObsidian
            width: parent.width
            spacing: Style.space(6)
            Text {
              text: "CURRENT GOAL"
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              font.bold: true
              font.letterSpacing: 0.8
            }
            TextArea {
              id: goalField
              width: parent.width
              height: Style.space(82)
              color: root.foreground
              selectionColor: root.watchBlue
              selectedTextColor: "white"
              placeholderText: "What outcome are you working toward?"
              placeholderTextColor: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
              wrapMode: TextEdit.Wrap
              textFormat: TextEdit.PlainText
              padding: Style.space(10)
              background: Rectangle {
                radius: 4
                color: root.cardColor
                border.width: goalField.activeFocus ? 1 : 0
                border.color: root.watchBlue
              }
              onTextChanged: if (activeFocus && !root.syncingFields) {
                root.manualSaveQueued = true
                saveManualGoalTimer.restart()
              }
              onActiveFocusChanged: if (!activeFocus) root.saveManualGoal()
            }
          }

          Column {
            visible: !root.effectiveObsidian
            width: parent.width
            spacing: Style.space(6)
            Text {
              text: "AVAILABLE TOOLS"
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              font.bold: true
              font.letterSpacing: 0.8
            }
            TextArea {
              id: toolsField
              width: parent.width
              height: Style.space(66)
              color: root.foreground
              selectionColor: root.watchBlue
              selectedTextColor: "white"
              placeholderText: "Codex, Browser, and any tool useful to the goal."
              placeholderTextColor: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              wrapMode: TextEdit.Wrap
              textFormat: TextEdit.PlainText
              padding: Style.space(10)
              background: Rectangle {
                radius: 4
                color: root.cardColor
                border.width: toolsField.activeFocus ? 1 : 0
                border.color: root.watchBlue
              }
              onTextChanged: if (activeFocus && !root.syncingFields) {
                root.manualSaveQueued = true
                saveManualGoalTimer.restart()
              }
              onActiveFocusChanged: if (!activeFocus) root.saveManualGoal()
            }
          }

          Column {
            visible: root.effectiveObsidian
            width: parent.width
            spacing: Style.space(5)
            PanelSectionHeader { text: "CURRENT GOAL"; foreground: root.foreground; fontFamily: root.fontFamily }
            Text {
              width: parent.width
              text: root.bounded(root.snapshot.goal || "No Current Goal block found yet.", 2000)
              textFormat: Text.PlainText
              color: root.snapshot.goal ? root.foreground : root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.body
              font.bold: !!root.snapshot.goal
              wrapMode: Text.WordWrap
              maximumLineCount: 4
              elide: Text.ElideRight
            }
            Text {
              width: parent.width
              text: root.bounded(root.snapshot.markdown_file || "Waiting for Obsidian to select a note", 4096)
              textFormat: Text.PlainText
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              elide: Text.ElideMiddle
            }
          }

          Text {
            visible: root.integrationNotice !== ""
            width: parent.width
            text: root.bounded(root.integrationNotice, 600)
            textFormat: Text.PlainText
            color: root.watchBlue
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
          }

          Text {
            visible: root.saveError !== "" || String(root.snapshot.error || "") !== ""
            width: parent.width
            text: root.bounded(root.saveError || root.snapshot.error || "", 600)
            textFormat: Text.PlainText
            color: root.saveError ? root.alertRed : root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
          }

          PanelSeparator { width: parent.width; foreground: root.foreground }
          PanelSectionHeader { text: "SESSION"; foreground: root.foreground; fontFamily: root.fontFamily }

          GridLayout {
            width: parent.width
            columns: 2
            columnSpacing: Style.space(10)
            rowSpacing: Style.space(8)
            MetricCell { title: "FOCUS SCORE"; value: String(root.metrics.focus_score || 0) + "%" }
            MetricCell { title: "WATCHING"; value: root.effectiveActive ? root.since(root.metrics.session_started_at, root.nowMs) : "—" }
            MetricCell { title: "CHECKS TODAY"; value: String(root.metrics.checks_today || 0) }
            MetricCell { title: "ALERTS TODAY"; value: String(root.metrics.alerts_today || 0) }
            MetricCell { title: "ON-GOAL STREAK"; value: root.effectiveActive ? root.since(root.metrics.streak_started_at, root.nowMs) : "—" }
            MetricCell { title: "LAST CHECK"; value: root.since(root.snapshot.last_check_at, root.nowMs) }
            MetricCell { title: "NEXT CHECK"; value: root.until(root.snapshot.next_check_at, root.nowMs) }
            MetricCell { title: "RETURN TIME"; value: root.metrics.average_return_seconds ? root.humanDuration(root.metrics.average_return_seconds) : "—" }
          }

          PanelSeparator { width: parent.width; foreground: root.foreground }
          PanelSectionHeader { text: "SETTINGS"; foreground: root.foreground; fontFamily: root.fontFamily }

          Rectangle {
            width: parent.width
            height: Style.space(56)
            radius: 5
            color: root.cardColor
            border.width: 1
            border.color: root.dim

            EyeIcon {
              width: Style.space(28)
              height: Style.space(19)
              anchors.left: parent.left
              anchors.leftMargin: Style.space(12)
              anchors.verticalCenter: parent.verticalCenter
              color: root.watchBlue
              dotColor: root.watchBlue
            }
            Column {
              anchors.left: parent.left
              anchors.leftMargin: Style.space(52)
              anchors.right: auditOpenArrow.left
              anchors.rightMargin: Style.space(10)
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(2)
              Text {
                text: "REQUEST AUDIT"
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                font.bold: true
                font.letterSpacing: 0.8
              }
              Text {
                text: "Screenshots, prompts, raw responses and failures"
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
              }
            }
            Text {
              id: auditOpenArrow
              anchors.right: parent.right
              anchors.rightMargin: Style.space(14)
              anchors.verticalCenter: parent.verticalCenter
              text: "→"
              color: root.watchBlue
              font.family: root.fontFamily
              font.pixelSize: Style.font.title
            }
            MouseArea {
              anchors.fill: parent
              cursorShape: Qt.PointingHandCursor
              onClicked: root.openAudit()
            }
          }

          Column {
            width: parent.width
            spacing: Style.space(5)
            Text { text: "Interval (minutes)"; color: root.dim; font.family: root.fontFamily; font.pixelSize: Style.font.caption }
            TextField {
              id: intervalField
              width: parent.width
              foreground: root.foreground
              accent: root.watchBlue
              placeholderText: "5"
              validator: IntValidator { bottom: 1; top: 1440 }
              onAccepted: { root.saveInterval(); keyCatcher.forceActiveFocus() }
              onActiveFocusChanged: if (!activeFocus) root.saveInterval()
            }
          }

          Column {
            width: parent.width
            spacing: Style.space(5)
            Text { text: "Model"; color: root.dim; font.family: root.fontFamily; font.pixelSize: Style.font.caption }
            TextField {
              id: modelField
              width: parent.width
              foreground: root.foreground
              accent: root.watchBlue
              placeholderText: "gemini-flash-lite-latest"
              onAccepted: { root.saveModel(); keyCatcher.forceActiveFocus() }
              onActiveFocusChanged: if (!activeFocus) root.saveModel()
            }
          }

          Column {
            width: parent.width
            spacing: Style.space(5)
            Text {
              id: apiKeyLabel
              text: "API Key" + (root.snapshot.api_key_set ? " · SET" : "")
              color: root.snapshot.api_key_set ? root.watchBlue : root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              font.bold: root.snapshot.api_key_set === true
              MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.LeftButton
                cursorShape: Qt.PointingHandCursor
                onDoubleClicked: Quickshell.execDetached(["omarchy", "launch", "browser", "https://aistudio.google.com/api-keys"])
              }
            }
            TextField {
              id: apiKeyField
              width: parent.width
              foreground: root.foreground
              accent: root.watchBlue
              echoMode: TextInput.Password
              placeholderText: "Enter a new key to replace the saved key"
              onAccepted: { root.saveApiKey(); keyCatcher.forceActiveFocus() }
              onActiveFocusChanged: if (!activeFocus) root.saveApiKey()
            }
          }

          Column {
            visible: root.effectiveObsidian
            width: parent.width
            spacing: Style.space(5)
            Text { text: "Synced Markdown File"; color: root.dim; font.family: root.fontFamily; font.pixelSize: Style.font.caption }
            TextField {
              id: pathField
              width: parent.width
              foreground: root.foreground
              accent: root.watchBlue
              placeholderText: "/path/to/current-note.md"
              onAccepted: { root.savePath(); keyCatcher.forceActiveFocus() }
              onActiveFocusChanged: if (!activeFocus) root.savePath()
            }
          }

          Text {
            width: parent.width
            text: "TODAY · " + String(root.metrics.prompt_tokens_today || 0) + " INPUT TOKENS · " + String(root.metrics.output_tokens_today || 0) + " OUTPUT TOKENS"
            color: root.dim
            opacity: 0.76
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            font.letterSpacing: 0.6
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
          }
        }
      }

      Item {
        id: auditView
        anchors.fill: parent
        visible: root.auditMode

        Column {
          anchors.fill: parent
          spacing: Style.space(10)

          Item {
            id: auditHeader
            width: parent.width
            height: Style.space(42)

            AuditAction {
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
              label: "← SETTINGS"
              onClicked: root.closeAudit()
            }

            Column {
              anchors.centerIn: parent
              spacing: Style.space(1)
              Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "REQUEST AUDIT"
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.title
                font.bold: true
                font.letterSpacing: 1.2
              }
              Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.auditTotal + " LOCAL RECORD" + (root.auditTotal === 1 ? "" : "S")
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                font.letterSpacing: 0.7
              }
            }

            AuditAction {
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              width: Style.space(root.clearAuditArmed ? 150 : 92)
              label: root.clearAuditArmed ? "CONFIRM CLEAR" : "CLEAR ALL"
              danger: true
              busy: auditClearProc.running
              enabled: !root.effectiveActive
              onClicked: root.clearAudit()
            }
          }

          Row {
            id: auditFilters
            width: parent.width
            height: Style.space(36)
            spacing: Style.space(7)

            Repeater {
              model: [
                {"label": "ALL", "value": "all"},
                {"label": "ON GOAL", "value": "on_goal"},
                {"label": "OFF GOAL", "value": "off_goal"},
                {"label": "PENDING", "value": "pending"},
                {"label": "ERRORS", "value": "error"}
              ]
              delegate: Rectangle {
                required property var modelData
                width: filterLabel.implicitWidth + Style.space(18)
                height: auditFilters.height
                radius: 4
                color: root.auditOutcome === modelData.value ? root.cardColor : "transparent"
                border.width: 1
                border.color: root.auditOutcome === modelData.value ? root.watchBlue : root.dim
                Text {
                  id: filterLabel
                  anchors.centerIn: parent
                  text: modelData.label
                  color: root.auditOutcome === modelData.value ? root.watchBlue : root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  font.bold: true
                  font.letterSpacing: 0.6
                }
                MouseArea {
                  anchors.fill: parent
                  cursorShape: Qt.PointingHandCursor
                  onClicked: {
                    root.auditOutcome = modelData.value
                    root.auditOffset = 0
                    root.queryAudit()
                  }
                }
              }
            }

            TextField {
              id: auditSearchField
              width: parent.width - x
              height: parent.height
              foreground: root.foreground
              accent: root.watchBlue
              placeholderText: "Filter goal, model, response or error…"
              onTextEdited: auditSearchTimer.restart()
            }
          }

          Text {
            visible: root.auditError !== ""
            width: parent.width
            text: root.bounded(root.auditError, 600)
            textFormat: Text.PlainText
            color: root.alertRed
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }

          Text {
            visible: root.effectiveActive
            width: parent.width
            text: "Stop watching before clearing the archive. Reading and filtering remain available."
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            horizontalAlignment: Text.AlignRight
          }

          Row {
            id: auditBody
            width: parent.width
            height: parent.height - auditHeader.height - auditFilters.height
              - auditFooter.height - (root.auditError === "" ? 0 : Style.space(20))
              - (root.effectiveActive ? Style.space(20) : 0)
              - parent.spacing * 3
            spacing: Style.space(10)

            Rectangle {
              width: Style.space(286)
              height: parent.height
              color: root.cardColor
              radius: 5
              border.width: 1
              border.color: root.dim

              ListView {
                id: auditList
                anchors.fill: parent
                anchors.margins: 1
                clip: true
                spacing: 1
                model: root.auditRecords
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                delegate: Rectangle {
                  required property var modelData
                  width: auditList.width
                  height: Style.space(82)
                  color: Number(root.selectedAudit.id || 0) === Number(modelData.id)
                    ? Qt.rgba(root.watchBlue.r, root.watchBlue.g, root.watchBlue.b, 0.12)
                    : "transparent"

                  Rectangle {
                    width: 3
                    height: parent.height
                    color: root.auditOutcomeColor(String(modelData.outcome || "error"))
                  }
                  Column {
                    anchors.left: parent.left
                    anchors.leftMargin: Style.space(12)
                    anchors.right: parent.right
                    anchors.rightMargin: Style.space(8)
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: Style.space(3)
                    Row {
                      width: parent.width
                      spacing: Style.space(7)
                      Text {
                        text: root.auditOutcomeLabel(String(modelData.outcome || "error"))
                        color: root.auditOutcomeColor(String(modelData.outcome || "error"))
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.caption
                        font.bold: true
                        font.letterSpacing: 0.6
                      }
                      Text {
                        text: root.auditTime(modelData.requested_at)
                        color: root.dim
                        font.family: root.fontFamily
                        font.pixelSize: Style.font.caption
                      }
                    }
                    Text {
                      width: parent.width
                      text: root.bounded(modelData.goal || "No goal", 180)
                      textFormat: Text.PlainText
                      color: root.foreground
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.body
                      font.bold: true
                      elide: Text.ElideRight
                    }
                    Text {
                      width: parent.width
                      text: root.bounded(modelData.model || modelData.error_code || "", 120)
                      textFormat: Text.PlainText
                      color: root.dim
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                      elide: Text.ElideRight
                    }
                  }
                  MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.loadAudit(Number(modelData.id))
                  }
                }

                Text {
                  visible: auditList.count === 0 && !auditQueryProc.running
                  anchors.centerIn: parent
                  width: parent.width - Style.space(30)
                  text: "No requests match this filter."
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.body
                  horizontalAlignment: Text.AlignHCenter
                  wrapMode: Text.WordWrap
                }
              }
            }

            Rectangle {
              width: parent.width - Style.space(296)
              height: parent.height
              color: root.cardColor
              radius: 5
              border.width: 1
              border.color: root.dim

              Flickable {
                anchors.fill: parent
                anchors.margins: Style.space(12)
                contentWidth: width
                contentHeight: auditDetailContent.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                Column {
                  id: auditDetailContent
                  width: parent.width
                  spacing: Style.space(10)

                  Text {
                    visible: !root.selectedAudit.id
                    width: parent.width
                    text: "Select a request to inspect its captured screen and exact model response."
                    color: root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                    wrapMode: Text.WordWrap
                    horizontalAlignment: Text.AlignHCenter
                  }

                  Row {
                    visible: !!root.selectedAudit.id
                    width: parent.width
                    spacing: Style.space(10)
                    Text {
                      text: root.auditOutcomeLabel(String(root.selectedAudit.outcome || "error"))
                      color: root.auditOutcomeColor(String(root.selectedAudit.outcome || "error"))
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.title
                      font.bold: true
                      font.letterSpacing: 1.0
                    }
                    Text {
                      text: root.auditTime(root.selectedAudit.requested_at)
                      color: root.dim
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                      anchors.verticalCenter: parent.verticalCenter
                    }
                  }

                  Text {
                    visible: !!root.selectedAudit.id
                    width: parent.width
                    text: root.bounded(root.selectedAudit.goal || "", 2000)
                    textFormat: Text.PlainText
                    color: root.foreground
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.title
                    font.bold: true
                    wrapMode: Text.WordWrap
                  }

                  Rectangle {
                    visible: !!root.selectedAudit.id
                    width: parent.width
                    height: Style.space(270)
                    radius: 4
                    color: "#05070A"
                    border.width: 1
                    border.color: root.dim
                    Image {
                      anchors.fill: parent
                      anchors.margins: 1
                      source: root.auditImageUrl(root.selectedAudit.image_path)
                      fillMode: Image.PreserveAspectFit
                      asynchronous: true
                      cache: false
                    }
                  }

                  GridLayout {
                    visible: !!root.selectedAudit.id
                    width: parent.width
                    columns: 4
                    columnSpacing: Style.space(12)
                    rowSpacing: Style.space(4)
                    AuditMeta { label: "MODEL"; value: root.selectedAudit.model || "—" }
                    AuditMeta { label: "HTTP"; value: root.selectedAudit.http_status || "—" }
                    AuditMeta { label: "LATENCY"; value: root.selectedAudit.latency_ms ? root.selectedAudit.latency_ms + " ms" : "—" }
                    AuditMeta { label: "RESPONSE"; value: (root.selectedAudit.response_bytes || 0) + " bytes" }
                    AuditMeta { label: "ERROR"; value: root.selectedAudit.error_code || "—" }
                    AuditMeta { label: "CAPTURE"; value: (root.selectedAudit.image_bytes || 0) + " bytes" }
                    AuditMeta { label: "INPUT TOKENS"; value: String(root.selectedAudit.prompt_tokens || 0) }
                    AuditMeta { label: "OUTPUT TOKENS"; value: String(root.selectedAudit.output_tokens || 0) }
                  }

                  Text {
                    visible: !!root.selectedAudit.id
                    text: "REQUEST PAYLOAD · API KEY OMITTED"
                    color: root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    font.bold: true
                    font.letterSpacing: 0.7
                  }
                  TextArea {
                    id: auditRequestArea
                    visible: !!root.selectedAudit.id
                    width: parent.width
                    height: Style.space(180)
                    readOnly: true
                    selectByMouse: true
                    text: root.bounded(root.selectedAudit.request_json || "", 24000)
                    textFormat: TextEdit.PlainText
                    wrapMode: TextEdit.WrapAnywhere
                    color: root.foreground
                    selectionColor: root.watchBlue
                    selectedTextColor: "white"
                    font.family: "Adwaita Mono"
                    font.pixelSize: Style.font.caption
                    background: Rectangle { color: "#05070A"; radius: 4; border.width: 1; border.color: root.dim }
                  }

                  Text {
                    visible: !!root.selectedAudit.id
                    text: "RAW MODEL RESPONSE · " + String(root.selectedAudit.raw_response_encoding || "utf-8").toUpperCase()
                    color: root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    font.bold: true
                    font.letterSpacing: 0.7
                  }
                  TextArea {
                    id: auditResponseArea
                    visible: !!root.selectedAudit.id
                    width: parent.width
                    height: Style.space(190)
                    readOnly: true
                    selectByMouse: true
                    text: root.bounded(root.selectedAudit.raw_response || "", 700000)
                    textFormat: TextEdit.PlainText
                    wrapMode: TextEdit.WrapAnywhere
                    color: root.foreground
                    selectionColor: root.watchBlue
                    selectedTextColor: "white"
                    font.family: "Adwaita Mono"
                    font.pixelSize: Style.font.caption
                    background: Rectangle { color: "#05070A"; radius: 4; border.width: 1; border.color: root.dim }
                  }

                  Text {
                    visible: !!root.selectedAudit.id
                    width: parent.width
                    text: root.selectedAudit.response_truncated
                      ? "Response exceeded the 512 KiB safety cap; the stored prefix is marked truncated."
                      : "SHA-256 · " + root.bounded(root.selectedAudit.response_sha256 || "EMPTY RESPONSE", 80)
                    textFormat: Text.PlainText
                    color: root.selectedAudit.response_truncated ? root.alertRed : root.dim
                    font.family: "Adwaita Mono"
                    font.pixelSize: Style.font.caption
                    wrapMode: Text.WordWrap
                  }
                }
              }
            }
          }

          Item {
            id: auditFooter
            width: parent.width
            height: Style.space(32)

            AuditAction {
              anchors.left: parent.left
              label: "← PREVIOUS"
              enabled: root.auditOffset > 0 && !auditQueryProc.running
              onClicked: {
                root.auditOffset = Math.max(0, root.auditOffset - root.auditLimit)
                root.queryAudit()
              }
            }
            Text {
              anchors.centerIn: parent
              text: root.auditTotal === 0 ? "0 / 0" : (root.auditOffset + 1) + "–"
                + Math.min(root.auditOffset + root.auditLimit, root.auditTotal) + " / " + root.auditTotal
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
            }
            AuditAction {
              anchors.right: parent.right
              label: "NEXT →"
              enabled: root.auditOffset + root.auditLimit < root.auditTotal && !auditQueryProc.running
              onClicked: {
                root.auditOffset += root.auditLimit
                root.queryAudit()
              }
            }
          }
        }
      }
    }
  }

  component MetricCell: Rectangle {
    property string title: ""
    property string value: "—"
    Layout.fillWidth: true
    implicitHeight: metricContent.implicitHeight + Style.space(16)
    color: root.cardColor
    radius: 4
    Column {
      id: metricContent
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      anchors.margins: Style.space(8)
      spacing: Style.space(2)
      Text {
        width: parent.width
        text: root.bounded(title, 80)
        textFormat: Text.PlainText
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.letterSpacing: 0.7
        elide: Text.ElideRight
      }
      Text {
        width: parent.width
        text: root.bounded(value, 120)
        textFormat: Text.PlainText
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        font.bold: true
        elide: Text.ElideRight
      }
    }
  }

  component AuditAction: Rectangle {
    property string label: "ACTION"
    property bool danger: false
    property bool busy: false
    signal clicked()
    width: Style.space(104)
    height: Style.space(32)
    radius: 4
    color: "transparent"
    opacity: enabled ? 1.0 : 0.4
    border.width: 1
    border.color: danger ? root.alertRed : root.dim
    Text {
      anchors.centerIn: parent
      text: parent.busy ? "WORKING…" : parent.label
      color: parent.danger ? root.alertRed : root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      font.bold: true
      font.letterSpacing: 0.5
    }
    MouseArea {
      anchors.fill: parent
      enabled: parent.enabled && !parent.busy
      cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
      onClicked: parent.clicked()
    }
  }

  component AuditMeta: Column {
    property string label: ""
    property string value: "—"
    Layout.fillWidth: true
    spacing: Style.space(2)
    Text {
      text: parent.label
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      font.letterSpacing: 0.6
    }
    Text {
      width: parent.width
      text: root.bounded(parent.value, 160)
      textFormat: Text.PlainText
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      font.bold: true
      elide: Text.ElideRight
    }
  }
}
