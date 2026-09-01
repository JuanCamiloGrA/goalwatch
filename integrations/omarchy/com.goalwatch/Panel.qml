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
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  property var snapshot: ({})
  property var metrics: ({})
  property string saveError: ""
  property bool alertActive: false
  property bool effectiveActive: false
  readonly property string statusText: snapshot.state === undefined ? "OFF" : String(snapshot.state)
  readonly property color eyeColor: alertActive ? alertRed : (effectiveActive ? watchBlue : dim)

  function parseState(content) {
    try {
      var parsed = JSON.parse(String(content || "{}"))
      snapshot = parsed && typeof parsed === "object" ? parsed : ({})
      metrics = parsed && parsed.metrics && typeof parsed.metrics === "object" ? parsed.metrics : ({})
      alertActive = parsed && parsed.alert && parsed.alert.active === true ? true : false
      effectiveActive = parsed && parsed.active === true ? true : false
      syncFields()
    } catch (e) {
      console.warn("GoalWatch: ignoring invalid runtime state", e)
    }
  }

  function syncFields() {
    if (intervalField && !intervalField.activeFocus)
      intervalField.text = String(snapshot.interval_minutes || 5)
    if (modelField && !modelField.activeFocus)
      modelField.text = String(snapshot.model || "gemini-flash-lite-latest")
    if (pathField && !pathField.activeFocus)
      pathField.text = String(snapshot.markdown_file || "")
  }

  function toggleWatching() {
    if (toggleProc.running) return
    effectiveActive = !effectiveActive
    toggleProc.running = true
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
    var value = Math.max(0, Number(seconds || 0))
    if (value < 60) return value + "s"
    var minutes = Math.floor(value / 60)
    if (minutes < 60) return minutes + "m"
    return Math.floor(minutes / 60) + "h " + (minutes % 60) + "m"
  }

  function since(iso) {
    if (!iso) return "—"
    var timestamp = Date.parse(String(iso))
    if (!isFinite(timestamp)) return "—"
    return humanDuration(Math.floor((Date.now() - timestamp) / 1000))
  }

  function until(iso) {
    if (!iso) return "—"
    var timestamp = Date.parse(String(iso))
    if (!isFinite(timestamp)) return "—"
    return humanDuration(Math.max(0, Math.ceil((timestamp - Date.now()) / 1000)))
  }

  function refreshState() {
    stateFile.reload()
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
        root.effectiveActive = root.snapshot.active === true ? true : false
        root.saveError = "Could not toggle GoalWatch."
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
    onStarted: {
      write(secret + "\n")
    }
    onExited: function(exitCode) {
      if (exitCode === 0) apiKeyField.text = ""
      else root.saveError = "Could not save the API key."
      secret = ""
      settleTimer.restart()
    }
  }

  Timer {
    id: settleTimer
    interval: 420
    repeat: false
    onTriggered: root.refreshState()
  }

  Timer {
    interval: 1000
    repeat: true
    running: root.opened
    onTriggered: timeTick.tick += 1
  }

  QtObject { id: timeTick; property int tick: 0 }

  implicitWidth: buttons.implicitWidth
  implicitHeight: buttons.implicitHeight

  Grid {
    id: buttons
    anchors.fill: parent
    columns: root.bar && root.bar.vertical ? 1 : 2

    BarIconButton {
      id: eyeButton
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
    contentWidth: panel.fittedContentWidth(Style.space(390))
    contentHeight: panel.fittedContentHeight(content.implicitHeight, Style.space(650))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: intervalField.activeFocus || modelField.activeFocus || pathField.activeFocus || apiKeyField.activeFocus
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
                color: root.alertActive ? root.alertRed : (root.effectiveActive ? root.watchBlue : root.dim)
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                font.bold: true
                font.letterSpacing: 1.2
                elide: Text.ElideRight
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

          Column {
            width: parent.width
            spacing: Style.space(5)
            PanelSectionHeader { text: "CURRENT GOAL"; foreground: root.foreground; fontFamily: root.fontFamily }
            Text {
              width: parent.width
              text: String(root.snapshot.goal || "No current goal found.")
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
              text: String(root.snapshot.markdown_source || "none").toUpperCase() + " · " + String(root.snapshot.markdown_file || "No Markdown file")
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              elide: Text.ElideMiddle
            }
          }

          PanelSeparator { width: parent.width; foreground: root.foreground }
          PanelSectionHeader { text: "SESSION"; foreground: root.foreground; fontFamily: root.fontFamily }

          GridLayout {
            width: parent.width
            columns: 2
            columnSpacing: Style.space(10)
            rowSpacing: Style.space(8)

            MetricCell { title: "FOCUS SCORE"; value: String(root.metrics.focus_score || 0) + "%" }
            MetricCell { title: "WATCHING"; value: root.effectiveActive ? root.since(root.metrics.session_started_at) : "—" }
            MetricCell { title: "CHECKS TODAY"; value: String(root.metrics.checks_today || 0) }
            MetricCell { title: "ALERTS TODAY"; value: String(root.metrics.alerts_today || 0) }
            MetricCell { title: "ON-GOAL STREAK"; value: root.effectiveActive ? root.since(root.metrics.streak_started_at) : "—" }
            MetricCell { title: "LAST CHECK"; value: root.since(root.snapshot.last_check_at) }
            MetricCell { title: "NEXT CHECK"; value: root.until(root.snapshot.next_check_at) }
            MetricCell { title: "RETURN TIME"; value: root.metrics.average_return_seconds ? root.humanDuration(root.metrics.average_return_seconds) : "—" }
            MetricCell { title: "API LATENCY"; value: root.metrics.median_latency_ms ? String(root.metrics.median_latency_ms) + " ms" : "—" }
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
            width: parent.width
            spacing: Style.space(5)
            Text { text: "Markdown File"; color: root.dim; font.family: root.fontFamily; font.pixelSize: Style.font.caption }
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
            visible: root.saveError !== "" || String(root.snapshot.error || "") !== ""
            width: parent.width
            text: root.saveError || String(root.snapshot.error || "")
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            wrapMode: Text.WordWrap
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
    color: Qt.rgba(root.foreground.r, root.foreground.g, root.foreground.b, 0.045)
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
        text: title
        color: root.dim
        font.family: root.fontFamily
        font.pixelSize: Style.font.caption
        font.letterSpacing: 0.7
        elide: Text.ElideRight
      }
      Text {
        width: parent.width
        text: value
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: Style.font.body
        font.bold: true
        elide: Text.ElideRight
      }
    }
  }
}
