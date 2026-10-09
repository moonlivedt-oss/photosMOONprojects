// Комната из подборки: пол и три стены из текстур, модели расставлены по полу в настоящем масштабе (см).
// Свойства ставит ui/room3d.py; мышь: тянуть - вращать, колесо - ближе/дальше, правая - сдвиг.
import QtQuick
import QtQuick3D
import QtQuick3D.Helpers
import QtQuick3D.AssetUtils

Item {
    id: root
    property var items: []                // [{src, x, z, rot, size, linear}]
    property real roomW: 600
    property real roomD: 600
    property real wallH: 280
    property url probe: ""
    property real exposure: 1.0
    property url floorBase: ""
    property url floorNormal: ""
    property url floorRough: ""
    property int floorRoughCh: 0
    property url wallBase: ""
    property url wallNormal: ""
    property url wallRough: ""
    property int wallRoughCh: 0
    property real floorTile: 1.5            // метров на один повтор текстуры
    property real wallTile: 2.0
    property color back: "#0d0d13"
    property bool plain: false
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

    function brighten(n) {
        var kids = n.children || []
        for (var i = 0; i < kids.length; i++) {
            var c = kids[i]
            if (c.materials !== undefined) {
                for (var j = 0; j < c.materials.length; j++) {
                    var m = c.materials[j]
                    if (m && m.baseColor !== undefined) {
                        var b = m.baseColor
                        m.baseColor = Qt.rgba(Math.pow(b.r, 1 / 2.2), Math.pow(b.g, 1 / 2.2), Math.pow(b.b, 1 / 2.2), b.a)
                    }
                }
            }
            if (c.mapPositionToScene !== undefined) brighten(c)
        }
    }

    function resetView() {
        orbit.position = Qt.vector3d(0, 80, 0)
        orbit.eulerRotation = Qt.vector3d(-28, 0, 0)
        cam.position = Qt.vector3d(0, 0, Math.max(roomW, roomD) * 1.35)
    }

    Rectangle {
        anchors.fill: parent
        visible: !root.plain
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.lighter(root.back, 1.9) }
            GradientStop { position: 1.0; color: root.back }
        }
    }

    View3D {
        id: view
        anchors.fill: parent
        environment: SceneEnvironment {
            backgroundMode: SceneEnvironment.Transparent
            lightProbe: root.probe != "" ? probeTex : null
            probeExposure: root.exposure
            tonemapMode: SceneEnvironment.TonemapModeAces
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.High
            aoEnabled: true
            aoStrength: 70
            aoDistance: 12
            aoSoftness: 50
        }
        Texture { id: probeTex; source: root.probe; mappingMode: Texture.LightProbe }

        Node {
            id: orbit
            PerspectiveCamera { id: cam; position: Qt.vector3d(0, 0, 900); clipNear: 1; clipFar: 50000; fieldOfView: 45 }
        }
        DirectionalLight {
            eulerRotation: Qt.vector3d(-55, -30, 0)
            brightness: root.probe == "" ? 1.4 : 0.45
            castsShadow: true
            shadowMapQuality: Light.ShadowMapQualityVeryHigh
            shadowFactor: 55
            softShadowQuality: Light.PCF16
            pcfFactor: 6
            csmNumSplits: 0
        }
        PointLight { position: Qt.vector3d(0, root.wallH - 20, 0); brightness: 0.4; quadraticFade: 0.3; color: "#ffe9cc" }

        // пол
        Model {
            source: "#Rectangle"
            eulerRotation.x: -90
            scale: Qt.vector3d(root.roomW / 100, root.roomD / 100, 1)
            receivesShadows: true
            materials: PrincipledMaterial {
                baseColor: root.floorBase != "" ? "white" : "#7a6a5a"
                baseColorMap: root.floorBase != "" ? fBase : null
                normalMap: root.floorNormal != "" ? fNorm : null
                roughness: 1.0
                roughnessMap: root.floorRough != "" ? fRough : null
                roughnessChannel: root.chan(root.floorRoughCh)
            }
        }
        Texture { id: fBase; source: root.floorBase; scaleU: root.roomW / 100 / root.floorTile; scaleV: root.roomD / 100 / root.floorTile; generateMipmaps: true; mipFilter: Texture.Linear }
        Texture { id: fNorm; source: root.floorNormal; scaleU: fBase.scaleU; scaleV: fBase.scaleV; generateMipmaps: true; mipFilter: Texture.Linear }
        Texture { id: fRough; source: root.floorRough; scaleU: fBase.scaleU; scaleV: fBase.scaleV; generateMipmaps: true; mipFilter: Texture.Linear }

        // три стены: задняя, левая, правая (перед открыт, чтобы видеть комнату)
        PrincipledMaterial {
            id: wallMat
            baseColor: root.wallBase != "" ? "white" : "#d9d4cb"
            baseColorMap: root.wallBase != "" ? wBase : null
            normalMap: root.wallNormal != "" ? wNorm : null
            roughness: 1.0
            roughnessMap: root.wallRough != "" ? wRough : null
            roughnessChannel: root.chan(root.wallRoughCh)
            cullMode: Material.NoCulling
        }
        Texture { id: wBase; source: root.wallBase; scaleU: root.roomW / 100 / root.wallTile; scaleV: root.wallH / 100 / root.wallTile; generateMipmaps: true; mipFilter: Texture.Linear }
        Texture { id: wNorm; source: root.wallNormal; scaleU: wBase.scaleU; scaleV: wBase.scaleV; generateMipmaps: true; mipFilter: Texture.Linear }
        Texture { id: wRough; source: root.wallRough; scaleU: wBase.scaleU; scaleV: wBase.scaleV; generateMipmaps: true; mipFilter: Texture.Linear }
        Model {
            source: "#Rectangle"; materials: wallMat; receivesShadows: true
            position: Qt.vector3d(0, root.wallH / 2, -root.roomD / 2)
            scale: Qt.vector3d(root.roomW / 100, root.wallH / 100, 1)
        }
        Model {
            source: "#Rectangle"; materials: wallMat; receivesShadows: true
            position: Qt.vector3d(-root.roomW / 2, root.wallH / 2, 0)
            eulerRotation.y: 90
            scale: Qt.vector3d(root.roomD / 100, root.wallH / 100, 1)
        }
        Model {
            source: "#Rectangle"; materials: wallMat; receivesShadows: true
            position: Qt.vector3d(root.roomW / 2, root.wallH / 2, 0)
            eulerRotation.y: -90
            scale: Qt.vector3d(root.roomD / 100, root.wallH / 100, 1)
        }

        // мебель
        Repeater3D {
            model: root.items
            delegate: Node {
                id: slot
                required property var modelData
                position: Qt.vector3d(modelData.x, 0, modelData.z)
                eulerRotation.y: modelData.rot
                RuntimeLoader {
                    id: ld
                    property bool fitted: false
                    source: slot.modelData.src
                    function fitOne() {
                        if (fitted || status !== RuntimeLoader.Success) return
                        fitted = true
                        if (slot.modelData.linear) root.brighten(ld)
                        scale = Qt.vector3d(1, 1, 1)
                        position = Qt.vector3d(0, 0, 0)
                        var parentRot = slot.eulerRotation
                        slot.eulerRotation = Qt.vector3d(0, 0, 0)
                        var box = root.sceneBox(ld, {ok: false})
                        slot.eulerRotation = parentRot
                        if (!box.ok) return
                        var lo = box.lo, hi = box.hi
                        // рамка в координатах сцены минус позиция слота
                        var dx = hi.x - lo.x, dy = hi.y - lo.y, dz = hi.z - lo.z
                        var m = Math.max(dx, dy, dz)
                        if (!(m > 0)) return
                        var s = slot.modelData.size / m
                        scale = Qt.vector3d(s, s, s)
                        var cx = (lo.x + hi.x) / 2 - slot.modelData.x, cz = (lo.z + hi.z) / 2 - slot.modelData.z
                        position = Qt.vector3d(-cx * s, -lo.y * s, -cz * s)
                        root.loaded += 1
                    }
                    onStatusChanged: if (status === RuntimeLoader.Success) Qt.callLater(fitOne)
                }
            }
        }
    }

    OrbitCameraController { anchors.fill: parent; origin: orbit; camera: cam }
}
