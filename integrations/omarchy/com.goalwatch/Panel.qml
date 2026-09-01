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
    contentWidth: panel.fittedContentWidth(Style.space(420))
    contentHeight: panel.fittedContentHeight(content.implicitHeight, Style.space(720))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: intervalField.activeFocus || modelField.activeFocus || pathField.activeFocus
        || apiKeyField.activeFocus || goalField.activeFocus || toolsField.activeFocus
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(t) {
        if (t === "t" || t === "T") root.toggleWatching()
        else if (t === "r" || t === "R") root.refreshState()
      }

      Flickable {
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
}
