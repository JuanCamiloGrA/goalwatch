import QtQuick

Item {
  id: root

  property color color: "#EDEFF2"
  property color dotColor: color
  property real strokeScale: 1.0

  onColorChanged: canvas.requestPaint()
  onDotColorChanged: canvas.requestPaint()
  onWidthChanged: canvas.requestPaint()
  onHeightChanged: canvas.requestPaint()

  Canvas {
    id: canvas
    anchors.fill: parent
    antialiasing: true

    onPaint: {
      var ctx = getContext("2d")
      ctx.reset()
      var scale = Math.min(width / 100, height / 64)
      var offsetX = (width - 100 * scale) / 2
      var offsetY = (height - 64 * scale) / 2
      function x(value) { return offsetX + value * scale }
      function y(value) { return offsetY + value * scale }
      ctx.strokeStyle = root.color
      ctx.fillStyle = root.color
      ctx.lineWidth = Math.max(1.1, 5 * scale * root.strokeScale)
      ctx.lineCap = "round"
      ctx.lineJoin = "round"

      ctx.beginPath()
      ctx.moveTo(x(4), y(32))
      ctx.bezierCurveTo(x(15), y(13), x(31), y(5), x(50), y(5))
      ctx.bezierCurveTo(x(69), y(5), x(85), y(13), x(96), y(32))
      ctx.bezierCurveTo(x(85), y(51), x(69), y(59), x(50), y(59))
      ctx.bezierCurveTo(x(31), y(59), x(15), y(51), x(4), y(32))
      ctx.closePath()
      ctx.stroke()

      ctx.lineWidth = Math.max(1, 4 * scale * root.strokeScale)
      ctx.beginPath()
      ctx.arc(x(50), y(32), 15 * scale, 0, Math.PI * 2)
      ctx.stroke()

      ctx.beginPath()
      ctx.moveTo(x(50), y(5))
      ctx.lineTo(x(50), y(17))
      ctx.moveTo(x(50), y(47))
      ctx.lineTo(x(50), y(59))
      ctx.moveTo(x(23), y(32))
      ctx.lineTo(x(35), y(32))
      ctx.moveTo(x(65), y(32))
      ctx.lineTo(x(77), y(32))
      ctx.stroke()

      ctx.fillStyle = root.dotColor
      ctx.beginPath()
      ctx.arc(x(50), y(32), 5 * scale, 0, Math.PI * 2)
      ctx.fill()
    }
  }
}
