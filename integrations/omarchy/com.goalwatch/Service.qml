import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

Item {
  id: root

  property var shell: null
  property var manifest: null
  readonly property string runtimeDir: Quickshell.env("XDG_RUNTIME_DIR") || ""
  readonly property string statePath: runtimeDir + "/goalwatch/state.json"
  readonly property color charcoal: "#080B10"
  readonly property color panel: "#0D1117"
  readonly property color line: "#29313B"
  readonly property color white: "#EDEFF2"
  readonly property color muted: "#9AA4B2"
  readonly property color alertRed: "#FF4D4F"
  property var snapshot: ({})
  property var alert: ({})
  property bool alertActive: false
  property string currentGoal: "Current goal"
  property string complement: "This activity is unrelated to the current goal."

  function parseState(content) {
    try {
      var parsed = JSON.parse(String(content || "{}"))
      snapshot = parsed && typeof parsed === "object" ? parsed : ({})
      alert = parsed && parsed.alert && typeof parsed.alert === "object" ? parsed.alert : ({})
      alertActive = alert.active === true
      currentGoal = parsed && parsed.goal ? String(parsed.goal).slice(0, 2000) : "Current goal"
      complement = alert.complement ? String(alert.complement).slice(0, 700) : "This activity is unrelated to the current goal."
    } catch (e) {
      console.warn("GoalWatch: ignoring invalid runtime state", e)
    }
  }

  function dismiss() {
    if (!dismissProc.running) dismissProc.running = true
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
    id: dismissProc
    command: ["goalwatch", "dismiss"]
  }

  Variants {
    model: Quickshell.screens

    PanelWindow {
      id: alertWindow
      required property var modelData
      screen: modelData
      visible: root.alertActive
      anchors { top: true; bottom: true; left: true; right: true }
      color: root.charcoal
      onVisibleChanged: if (visible) Qt.callLater(function() { inputGuard.forceActiveFocus() })

      WlrLayershell.namespace: "goalwatch-alert"
      WlrLayershell.layer: WlrLayer.Overlay
      WlrLayershell.keyboardFocus: WlrKeyboardFocus.Exclusive
      exclusionMode: ExclusionMode.Ignore

      Rectangle {
        anchors.fill: parent
        color: root.charcoal

        EyeIcon {
          width: Math.min(920, parent.width * 0.56)
          height: width * 0.64
          anchors.right: parent.right
          anchors.rightMargin: -width * 0.18
          anchors.bottom: parent.bottom
          anchors.bottomMargin: -height * 0.22
          color: root.alertRed
          dotColor: root.alertRed
          opacity: 0.035
          strokeScale: 0.8
        }

        Rectangle {
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.top: parent.top
          height: Math.max(42, Math.min(52, parent.height * 0.052))
          color: root.alertRed

          Text {
            anchors.left: parent.left
            anchors.leftMargin: 32
            anchors.verticalCenter: parent.verticalCenter
            text: "GOALWATCH"
            color: root.charcoal
            font.family: "Adwaita Mono"
            font.pixelSize: 14
            font.bold: true
            font.letterSpacing: 1.8
          }

          Text {
            anchors.centerIn: parent
            text: "ACTIVITY OUTSIDE CURRENT GOAL"
            color: root.charcoal
            font.family: "Adwaita Mono"
            font.pixelSize: 13
            font.bold: true
            font.letterSpacing: 1.2
          }

          Text {
            anchors.right: parent.right
            anchors.rightMargin: 32
            anchors.verticalCenter: parent.verticalCenter
            text: "INTERVENTION ACTIVE"
            color: root.charcoal
            font.family: "Adwaita Mono"
            font.pixelSize: 12
            font.bold: true
            font.letterSpacing: 1.2
          }
        }

        Rectangle {
          anchors.fill: parent
          anchors.margins: 28
          anchors.topMargin: 74
          color: "transparent"
          border.width: 1
          border.color: root.line
        }

        Rectangle {
          anchors.left: parent.left
          anchors.leftMargin: 28
          anchors.top: parent.top
          anchors.topMargin: 74
          width: Math.min(220, parent.width * 0.16)
          height: 3
          color: root.alertRed
        }

        Rectangle {
          anchors.right: parent.right
          anchors.rightMargin: 28
          anchors.bottom: parent.bottom
          anchors.bottomMargin: 28
          width: Math.min(220, parent.width * 0.16)
          height: 3
          color: root.alertRed
        }

        Item {
          id: inputGuard
          anchors.fill: parent
          focus: root.alertActive
          Keys.priority: Keys.BeforeItem
          Keys.onPressed: function(event) { event.accepted = true }

          MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.AllButtons
            hoverEnabled: true
            onClicked: function(mouse) { mouse.accepted = true }
            onWheel: function(wheel) { wheel.accepted = true }
          }

          Item {
            id: content
            width: Math.min(parent.width - 128, 1180)
            height: Math.min(parent.height - 160, 660)
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.verticalCenter: parent.verticalCenter
            anchors.verticalCenterOffset: 22

            Item {
              id: statusHeader
              anchors.left: parent.left
              anchors.right: parent.right
              anchors.top: parent.top
              height: 70

              Rectangle {
                id: pulse
                width: 12
                height: 12
                radius: 6
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                color: root.alertRed

                SequentialAnimation on opacity {
                  loops: Animation.Infinite
                  NumberAnimation { from: 1.0; to: 0.35; duration: 650 }
                  NumberAnimation { from: 0.35; to: 1.0; duration: 650 }
                }
              }

              Text {
                anchors.left: pulse.right
                anchors.leftMargin: 14
                anchors.verticalCenter: parent.verticalCenter
                text: "OFF GOAL"
                color: root.alertRed
                font.family: "Adwaita Mono"
                font.pixelSize: Math.max(20, Math.min(28, alertWindow.height * 0.03))
                font.bold: true
                font.letterSpacing: 2.5
              }

              Text {
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                text: "GOALWATCH / PRIORITY INTERRUPT"
                color: root.muted
                font.family: "Adwaita Mono"
                font.pixelSize: 12
                font.letterSpacing: 1.2
              }
            }

            Rectangle {
              id: headerRule
              anchors.left: parent.left
              anchors.right: parent.right
              anchors.top: statusHeader.bottom
              height: 1
              color: root.line
            }

            Item {
              id: body
              anchors.left: parent.left
              anchors.right: parent.right
              anchors.top: headerRule.bottom
              anchors.bottom: actionFooter.top

              Item {
                id: brandPane
                anchors.left: parent.left
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                width: Math.min(300, parent.width * 0.29)

                Rectangle {
                  width: Math.min(parent.width - 24, 250)
                  height: Math.min(width * 0.72, parent.height * 0.58)
                  anchors.horizontalCenter: parent.horizontalCenter
                  anchors.verticalCenter: parent.verticalCenter
                  anchors.verticalCenterOffset: -24
                  color: root.panel
                  border.width: 1
                  border.color: root.line

                  Rectangle {
                    anchors.left: parent.left
                    anchors.top: parent.top
                    width: 52
                    height: 3
                    color: root.alertRed
                  }

                  Rectangle {
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    width: 52
                    height: 3
                    color: root.alertRed
                  }

                  EyeIcon {
                    width: parent.width * 0.72
                    height: width * 0.64
                    anchors.centerIn: parent
                    color: root.alertRed
                    dotColor: root.alertRed
                    strokeScale: 0.82
                  }
                }

                Text {
                  anchors.horizontalCenter: parent.horizontalCenter
                  anchors.bottom: parent.bottom
                  anchors.bottomMargin: 28
                  text: "INTERVENTION ACTIVE"
                  color: root.muted
                  font.family: "Adwaita Mono"
                  font.pixelSize: 11
                  font.letterSpacing: 1.6
                }
              }

              Rectangle {
                id: verticalRule
                anchors.left: brandPane.right
                anchors.top: parent.top
                anchors.topMargin: 34
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 34
                width: 1
                color: root.line
              }

              Column {
                id: details
                anchors.left: verticalRule.right
                anchors.leftMargin: Math.max(34, parent.width * 0.04)
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: 13

                Text {
                  width: parent.width
                  text: "CURRENT GOAL"
                  color: root.muted
                  font.family: "Adwaita Mono"
                  font.pixelSize: 12
                  font.letterSpacing: 1.5
                }

                Text {
                  width: parent.width
                  text: root.currentGoal
                  textFormat: Text.PlainText
                  color: root.white
                  wrapMode: Text.WordWrap
                  maximumLineCount: 3
                  elide: Text.ElideRight
                  font.family: "Inter"
                  font.pixelSize: Math.max(28, Math.min(43, alertWindow.height * 0.043))
                  font.bold: true
                }

                Rectangle {
                  width: parent.width
                  height: 1
                  color: root.line
                }

                Rectangle {
                  width: parent.width
                  height: Math.max(128, explanation.implicitHeight + 58)
                  color: root.panel
                  border.width: 1
                  border.color: root.line

                  Rectangle {
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    width: 4
                    color: root.alertRed
                  }

                  Text {
                    id: explanationLabel
                    anchors.left: parent.left
                    anchors.leftMargin: 24
                    anchors.right: parent.right
                    anchors.rightMargin: 22
                    anchors.top: parent.top
                    anchors.topMargin: 18
                    text: "WHY GOALWATCH INTERRUPTED"
                    color: root.alertRed
                    font.family: "Adwaita Mono"
                    font.pixelSize: 11
                    font.bold: true
                    font.letterSpacing: 1.2
                  }

                  Text {
                    id: explanation
                    anchors.left: parent.left
                    anchors.leftMargin: 24
                    anchors.right: parent.right
                    anchors.rightMargin: 22
                    anchors.top: explanationLabel.bottom
                    anchors.topMargin: 11
                    text: root.complement
                    textFormat: Text.PlainText
                    color: root.white
                    opacity: 0.92
                    wrapMode: Text.WordWrap
                    maximumLineCount: 4
                    elide: Text.ElideRight
                    font.family: "Inter"
                    font.pixelSize: Math.max(16, Math.min(21, alertWindow.height * 0.022))
                  }
                }
              }
            }

            Item {
              id: actionFooter
              anchors.left: parent.left
              anchors.right: parent.right
              anchors.bottom: parent.bottom
              height: 98

              Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                height: 1
                color: root.line
              }

              Text {
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                text: "Monitoring resumes after acknowledgement."
                color: root.muted
                font.family: "Inter"
                font.pixelSize: 13
              }

              Rectangle {
                id: returnButton
                width: Math.min(390, parent.width * 0.42)
                height: 62
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                color: returnMouse.containsMouse ? root.white : root.alertRed
                border.width: 1
                border.color: returnMouse.containsMouse ? root.white : root.alertRed

                Behavior on color { ColorAnimation { duration: 90 } }

                Text {
                  anchors.centerIn: parent
                  text: "I’LL GET BACK TO WORK"
                  color: root.charcoal
                  font.family: "Adwaita Mono"
                  font.pixelSize: 13
                  font.bold: true
                  font.letterSpacing: 1.3
                }

                MouseArea {
                  id: returnMouse
                  anchors.fill: parent
                  hoverEnabled: true
                  cursorShape: Qt.PointingHandCursor
                  onClicked: root.dismiss()
                }
              }
            }
          }
        }
      }
    }
  }
}
