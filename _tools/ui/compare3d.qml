// Сравнение 2-4 ассетов рядом: модели на одном подиуме в одном масштабе (настоящем, если известен) или
// текстуры на одинаковых шарах; один свет, одна камера, вращаются вместе. Свойства ставит ui/compare3d.py.
import QtQuick
import QtQuick3D
import QtQuick3D.Helpers
import QtQuick3D.AssetUtils

Item {
    id: root
    property var items: []        // [{kind: model|tex, src, size, base, normal, rough, roughCh, name, sub}]
    property real slot: 260       // ширина места под один ассет
    property url probe: ""
    property real exposure: 1.0
    property color back: "#0d0d13"
    property color accent: "#a897ff"
    property bool spin: false
    property real yaw: 0
    property int loaded: 0

    function chan(i) { return [Material.R, Material.G, Material.B, Material.A][i] }

    function sceneBox(n, box) {
        var kids = n.children || []
        for (var i = 0; i < kids.length; i++) {
            var c = kids[i]
            if (c.bounds !== undefined && c.source !== undefined && c.mapPositionToScene !== undefined) {
                var b = c.bounds
                if (b.maximum.x >= b.minimum.x) {
                    for (var k = 0; k < 8; k++) {
                        var p = c.mapPositionToScene(Qt.vector3d(k & 1 ? b.maximum.x : b.minimum.x,
                                                                 k & 2 ? b.maximum.y : b.minimum.y,
                                                                 k & 4 ? b.maximum.z : b.minimum.z))
                        if (!box.ok) { box.lo = p; box.hi = p; box.ok = true }
                        box.lo = Qt.vector3d(Math.min(box.lo.x, p.x), Math.min(box.lo.y, p.y), Math.min(box.lo.z, p.z))
                        box.hi = Qt.vector3d(Math.max(box.hi.x, p.x), Math.max(box.hi.y, p.y), Math.max(box.hi.z, p.z))
                    }
                }
            }
            if (c.mapPositionToScene !== undefined) sceneBox(c, box)
        }
        return box
    }

    function slotX(i) { return (i - (items.length - 1) / 2) * slot }

    function resetView() {
        var w = Math.max(1, items.length) * slot
        orbit.position = Qt.vector3d(0, maxH() / 2, 0)
        orbit.eulerRotation = Qt.vector3d(-14, 0, 0)
        cam.position = Qt.vector3d(0, 0, Math.max(380, w * 0.95))
    }
    function maxH() {
        var h = 0
        for (var i = 0; i < items.length; i++) h = Math.max(h, items[i].size || 200)
        return Math.min(h, slot * 1.6)
    }

    FrameAnimation { running: root.spin; onTriggered: root.yaw += frameTime * 30 }

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.lighter(root.back, 1.8) }
            GradientStop { position: 1.0; color: root.back }
        }
    }

    View3D {
        id: view
        anchors.fill: parent
        camera: cam
        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Transparent
            lightProbe: root.probe != "" ? probeTex : null
            probeExposure: root.exposure
            tonemapMode: SceneEnvironment.TonemapModeAces
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.High
            aoEnabled: true
            aoStrength: 50
            aoDistance: 6
        }
        Texture { id: probeTex; source: root.probe; mappingMode: Texture.LightProbe }

        Node {
            id: orbit
            PerspectiveCamera { id: cam; position: Qt.vector3d(0, 0, 700); clipNear: 1; clipFar: 50000; fieldOfView: 38 }
        }
        DirectionalLight { visible: root.probe == ""; eulerRotation: Qt.vector3d(-35, -30, 0); brightness: 1.2 }
        DirectionalLight {
            eulerRotation: Qt.vector3d(-60, 20, 0); brightness: 0.4; castsShadow: true
            shadowMapQuality: Light.ShadowMapQualityHigh; shadowFactor: 40
        }

        // подиум под всеми
        Model {
            source: "#Cylinder"
            position: Qt.vector3d(0, -3, 0)
            scale: Qt.vector3d((root.items.length * root.slot / 2 + 30) / 50, 0.06, 2.6)  // цилиндр - радиус 50
            receivesShadows: true
            materials: PrincipledMaterial { baseColor: Qt.darker(root.back, 0.7); roughness: 0.6 }
        }

        Repeater3D {
            model: root.items
            delegate: Node {
                id: slotNode
                required property var modelData
                required property int index
                position: Qt.vector3d(root.slotX(index), 0, 0)
                eulerRotation.y: root.yaw
                RuntimeLoader {
                    id: ld
                    visible: slotNode.modelData.kind === "model"
                    source: slotNode.modelData.kind === "model" ? slotNode.modelData.src : ""
                    property bool fitted: false
                    function fitOne() {
                        if (fitted || status !== RuntimeLoader.Success) return
                        fitted = true
                        scale = Qt.vector3d(1, 1, 1)
                        position = Qt.vector3d(0, 0, 0)
                        var rot = slotNode.eulerRotation
                        slotNode.eulerRotation = Qt.vector3d(0, 0, 0)
                        var box = root.sceneBox(ld, {ok: false})
                        slotNode.eulerRotation = rot
                        if (!box.ok) return
                        var lo = box.lo, hi = box.hi, ox = root.slotX(slotNode.index)
                        var m = Math.max(hi.x - lo.x, hi.y - lo.y, hi.z - lo.z)
                        if (!(m > 0)) return
                        var s = (slotNode.modelData.size || 200) / m
                        scale = Qt.vector3d(s, s, s)
                        position = Qt.vector3d(-((lo.x + hi.x) / 2 - ox) * s, -lo.y * s, -((lo.z + hi.z) / 2) * s)
                        root.loaded += 1
                    }
                    onStatusChanged: if (status === RuntimeLoader.Success) Qt.callLater(fitOne)
                }
                Model {
                    visible: slotNode.modelData.kind === "tex"
                    source: "#Sphere"
                    position: Qt.vector3d(0, 85, 0)
                    scale: Qt.vector3d(1.6, 1.6, 1.6)
                    castsShadows: true
                    materials: PrincipledMaterial {
                        lighting: PrincipledMaterial.FragmentLighting
                        baseColorMap: Texture { source: slotNode.modelData.base || ""; scaleU: 2; scaleV: 2; generateMipmaps: true; mipFilter: Texture.Linear }
                        normalMap: slotNode.modelData.normal ? nrm : null
                        roughness: 1.0
                        roughnessMap: slotNode.modelData.rough ? rgh : null
                        roughnessChannel: root.chan(slotNode.modelData.roughCh || 0)
                    }
                    Texture { id: nrm; source: slotNode.modelData.normal || ""; scaleU: 2; scaleV: 2 }
                    Texture { id: rgh; source: slotNode.modelData.rough || ""; scaleU: 2; scaleV: 2 }
                }
            }
        }
    }

    // подписи под каждым: номер, имя и сведения
    Repeater {
        model: root.items
        delegate: Rectangle {
            id: tag
            required property var modelData
            required property int index
            radius: 10; color: "#e014141c"; border.color: Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.5)
            width: col.implicitWidth + 22; height: col.implicitHeight + 12
            Column {
                id: col
                anchors.centerIn: parent
                spacing: 1
                Text { text: (tag.index + 1) + ". " + tag.modelData.name; color: "#f4f2fb"; font.pixelSize: 13; font.weight: Font.DemiBold; anchors.horizontalCenter: parent.horizontalCenter }
                Text { text: tag.modelData.sub || ""; color: "#a8a4bc"; font.pixelSize: 11; anchors.horizontalCenter: parent.horizontalCenter }
            }
            FrameAnimation {
                running: true
                onTriggered: {
                    var p = view.mapFrom3DScene(Qt.vector3d(root.slotX(tag.index), -8, 0))
                    tag.x = p.x - tag.width / 2
                    tag.y = Math.min(root.height - tag.height - 8, p.y + 10)
                }
            }
        }
    }

    OrbitCameraController { anchors.fill: parent; origin: orbit; camera: cam }
}
