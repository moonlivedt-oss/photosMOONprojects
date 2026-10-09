// Просмотр ассетов Unreal: модель (FBX через assimp), текстура на фигуре, HDRI-панорама изнутри.
// Свойства ставит ui/viewer3d.py; мышь: тянуть - вращать, колесо - ближе/дальше, правая - сдвиг.
// Модель и фигура стоят на полу (y = 0), камера крутится вокруг их середины.
import QtQuick
import QtQuick3D
import QtQuick3D.Helpers
import QtQuick3D.AssetUtils

Item {
    id: root
    property string mode: "model"          // model | tex | hdri
    property url modelSource: ""
    property url probe: ""                 // HDRI для освещения (и фон в режиме hdri)
    property bool showSky: false           // фон-небо за моделью/текстурой
    property real exposure: 1.0
    property real skyRotation: 0
    property string shape: "sphere"        // sphere | cube | plane
    property real tiling: 1.0
    property bool wire: false
    property bool floor: true              // пол с тенью и сеткой
    property bool spin: false              // модель вращается сама, как на подставке
    property bool mirrorBall: false        // в режиме hdri: зеркальный и матовый шары - как небо светит
    property url flat: ""                  // картинка поверх сцены: одна карта текстуры или развёртка HDRI
    property bool flatTile: true           // карту - плиткой, развёртку - целиком
    property string flatTitle: ""
    property url baseMap: ""
    property url normalMap: ""
    property url roughMap: ""
    property int roughChannel: 0           // 0 R, 1 G, 2 B, 3 A
    property url metalMap: ""
    property int metalChannel: 0
    property url aoMap: ""
    property int aoChannel: 0
    property url heightMap: ""
    property real heightAmount: 0.0
    property string status: ""
    property string sizeText: ""           // размеры модели в её единицах - для подписи в окне
    property color back: "#0d0d13"
    property bool plain: false             // без фона - для рендера превью с прозрачностью
    property color accent: "#a897ff"
    property real height3d: 200
    property real camScale: 1.0            // дальше камера во столько раз (рендер превью: модель целиком)
    property bool linearColors: false     // цвета материалов в файле линейные (Quaternius) - на экран через гамму
    property bool tryOn: false            // примерка: материал текстуры (texMat) на все части модели
    property var origMats: []             // [{model, mats}] - вернуть родные материалы
    property bool fitted: false            // подгонка под кадр - один раз на загрузку: смена масштаба
                                           // меняет рамку модели, и без флага подгонка шла по кругу (дрожь)            // высота того, что на полу - вокруг середины крутится камера

    function chan(i) { return [Material.R, Material.G, Material.B, Material.A][i] }

    // рамка модели на сцене: углы рамок всех частей через их собственные повороты и масштабы
    // (у FBX внутри часто свой поворот Z-вверх и масштаб 0.01 - рамка загрузчика их не учитывает)
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

    // линейный цвет -> экранный (как сделает Unreal): иначе тёмно-красный диван выходит почти чёрным
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

    function models(n, out) {
        var kids = n.children || []
        for (var i = 0; i < kids.length; i++) {
            if (kids[i].materials !== undefined && kids[i].source !== undefined) out.push(kids[i])
            if (kids[i].mapPositionToScene !== undefined) models(kids[i], out)
        }
        return out
    }

    function applyTryOn() {
        restoreMats()
        if (!tryOn || mode !== "model" || loader.status !== RuntimeLoader.Success) return
        var saved = []
        var ms = models(loader, [])
        for (var i = 0; i < ms.length; i++) {
            var keep = []
            for (var j = 0; j < ms[i].materials.length; j++) keep.push(ms[i].materials[j])
            saved.push({model: ms[i], mats: keep})
            ms[i].materials = [texMat]
        }
        origMats = saved
    }

    function restoreMats() {
        for (var i = 0; i < origMats.length; i++) origMats[i].model.materials = origMats[i].mats
        origMats = []
    }

    onTryOnChanged: applyTryOn()

    function fit() {
        if (fitted || mode !== "model" || loader.status !== RuntimeLoader.Success) return
        fitted = true
        if (linearColors) brighten(loader)
        if (tryOn) applyTryOn()
        turn.eulerRotation = Qt.vector3d(0, 0, 0)
        loader.scale = Qt.vector3d(1, 1, 1)
        loader.position = Qt.vector3d(0, 0, 0)
        var box = sceneBox(loader, {ok: false})
        var lo, hi
        if (box.ok) { lo = box.lo; hi = box.hi }
        else { lo = loader.bounds.minimum; hi = loader.bounds.maximum }
        var dx = hi.x - lo.x, dy = hi.y - lo.y, dz = hi.z - lo.z
        var m = Math.max(dx, dy, dz)
        if (!(m > 0)) return
        var s = 200 / m
        loader.scale = Qt.vector3d(s, s, s)
        // по центру по x и z, низом на пол
        loader.position = Qt.vector3d(-(lo.x + dx / 2) * s, -lo.y * s, -(lo.z + dz / 2) * s)
        height3d = dy * s
        sizeText = [dx, dy, dz].map(function (v) { return v < 10 ? v.toFixed(2) : Math.round(v) }).join(" x ")
        resetView()
    }

    function resetView() {
        var h = mode === "tex" ? (shape === "plane" ? 0 : 180) : mode === "hdri" ? 0 : height3d
        orbit.position = Qt.vector3d(0, h / 2, 0)
        orbit.eulerRotation = mode === "hdri" ? Qt.vector3d(0, 0, 0)
                            : mode === "tex" && shape === "plane" ? Qt.vector3d(-55, 20, 0) : Qt.vector3d(-16, 32, 0)
        // узкое высокое окно (панель вкладки) - камера дальше, иначе предмет обрезан по бокам
        var aspect = view.width > 0 ? view.height / view.width : 1
        cam.position = Qt.vector3d(0, 0, mode === "hdri" ? 0.01 : 420 * camScale * Math.max(1, aspect * 1.05))
        cam.fieldOfView = mode === "hdri" ? 75 : 40
        if (mode === "hdri") { cam.clipNear = 0.01; cam.clipFar = 1000 }
    }

    onModelSourceChanged: { fitted = false; origMats = [] }
    onModeChanged: { if (mode !== "model") height3d = 200; resetView() }
    onShapeChanged: resetView()

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
            backgroundMode: (root.mode === "hdri" || root.showSky) && root.probe != "" ? SceneEnvironment.SkyBox : SceneEnvironment.Transparent
            lightProbe: root.probe != "" ? probeTex : null
            probeExposure: root.exposure
            probeOrientation: Qt.vector3d(0, root.skyRotation, 0)
            tonemapMode: SceneEnvironment.TonemapModeAces
            antialiasingMode: SceneEnvironment.MSAA
            antialiasingQuality: SceneEnvironment.High
            specularAAEnabled: true
            aoEnabled: root.mode !== "hdri"
            aoStrength: 60
            aoDistance: 6
            aoSoftness: 40
        }
        Texture { id: probeTex; source: root.probe; mappingMode: Texture.LightProbe }

        Node {
            id: orbit
            objectName: "orbit"
            PerspectiveCamera {
                id: cam; position: Qt.vector3d(0, 0, 420); clipNear: 1; clipFar: 20000
                // HDRI: зеркальный и матовый шары перед камерой - видно, как небо освещает сцену
                Node {
                    visible: root.mode === "hdri" && root.mirrorBall
                    position: Qt.vector3d(0, -12, -60)
                    Model {
                        source: "#Sphere"; position: Qt.vector3d(-12, 0, 0); scale: Qt.vector3d(0.19, 0.19, 0.19)
                        materials: PrincipledMaterial { baseColor: "white"; metalness: 1.0; roughness: 0.02 }
                    }
                    Model {
                        source: "#Sphere"; position: Qt.vector3d(12, 0, 0); scale: Qt.vector3d(0.19, 0.19, 0.19)
                        materials: PrincipledMaterial { baseColor: "#d8d8d8"; metalness: 0.0; roughness: 0.9 }
                    }
                }
            }
        }

        // без HDRI - простой свет; с HDRI - только слабый ключевой свет ради тени на полу
        DirectionalLight {
            eulerRotation: Qt.vector3d(-50, -35, 0)
            brightness: root.probe == "" ? 1.6 : (root.floor ? 0.35 : 0)
            castsShadow: root.floor && root.mode !== "hdri"
            shadowMapQuality: Light.ShadowMapQualityVeryHigh
            shadowFactor: 60
            softShadowQuality: Light.PCF16
            pcfFactor: 4
            shadowBias: 5
            csmNumSplits: 0
        }
        DirectionalLight { visible: root.probe == ""; eulerRotation: Qt.vector3d(-10, 150, 0); brightness: 0.5 }

        // пол: принимает тень, сетка - отдельно и поверх
        Model {
            visible: root.floor && root.mode !== "hdri"
            source: "#Rectangle"
            eulerRotation.x: -90
            scale: Qt.vector3d(12, 12, 1)
            receivesShadows: true
            castsShadows: false
            materials: PrincipledMaterial {
                baseColor: Qt.darker(root.back, 0.75)
                roughness: 0.85
                metalness: 0
            }
        }
        InfiniteGrid {
            visible: root.floor && root.mode !== "hdri"
            gridInterval: 25
        }

        Node {
            id: turn
            objectName: "turn"
            FrameAnimation {
                running: root.spin && root.mode !== "hdri"
                onTriggered: turn.eulerRotation.y += frameTime * 30
            }

            RuntimeLoader {
                id: loader
                visible: root.mode === "model"
                source: root.mode === "model" ? root.modelSource : ""
                onStatusChanged: {
                    if (status === RuntimeLoader.Error) root.status = "Не открылось: " + errorString
                    else if (status === RuntimeLoader.Success) { root.status = ""; Qt.callLater(root.fit) }
                }
                onBoundsChanged: Qt.callLater(root.fit)
            }

            Model {
                id: sample
                visible: root.mode === "tex"
                source: root.shape === "cube" ? "#Cube" : root.shape === "plane" ? "#Rectangle" : "#Sphere"
                position: Qt.vector3d(0, root.shape === "plane" ? 0.5 : 90, 0)
                scale: root.shape === "plane" ? Qt.vector3d(3, 3, 1) : Qt.vector3d(1.8, 1.8, 1.8)
                eulerRotation: root.shape === "plane" ? Qt.vector3d(-90, 0, 0) : Qt.vector3d(0, 0, 0)
                castsShadows: root.shape !== "plane"
                materials: PrincipledMaterial {
                    id: texMat
                    lighting: PrincipledMaterial.FragmentLighting
                    baseColor: root.baseMap != "" ? "white" : "#999999"
                    baseColorMap: root.baseMap != "" ? tBase : null
                    normalMap: root.normalMap != "" ? tNorm : null
                    roughness: 1.0
                    roughnessMap: root.roughMap != "" ? tRough : null
                    roughnessChannel: root.chan(root.roughChannel)
                    metalness: root.metalMap != "" ? 1.0 : 0.0
                    metalnessMap: root.metalMap != "" ? tMetal : null
                    metalnessChannel: root.chan(root.metalChannel)
                    occlusionMap: root.aoMap != "" ? tAo : null
                    occlusionChannel: root.chan(root.aoChannel)
                    occlusionAmount: 1.0
                    heightMap: root.heightMap != "" && root.heightAmount > 0 ? tHeight : null
                    heightAmount: root.heightAmount
                    cullMode: root.shape === "plane" ? Material.NoCulling : Material.BackFaceCulling
                }
            }
        }
        Texture { id: tBase; source: root.baseMap; scaleU: root.tiling; scaleV: root.tiling; generateMipmaps: true; mipFilter: Texture.Linear }
        Texture { id: tNorm; source: root.normalMap; scaleU: root.tiling; scaleV: root.tiling; generateMipmaps: true; mipFilter: Texture.Linear }
        Texture { id: tRough; source: root.roughMap; scaleU: root.tiling; scaleV: root.tiling; generateMipmaps: true; mipFilter: Texture.Linear }
        Texture { id: tMetal; source: root.metalMap; scaleU: root.tiling; scaleV: root.tiling; generateMipmaps: true; mipFilter: Texture.Linear }
        Texture { id: tAo; source: root.aoMap; scaleU: root.tiling; scaleV: root.tiling; generateMipmaps: true; mipFilter: Texture.Linear }
        Texture { id: tHeight; source: root.heightMap; scaleU: root.tiling; scaleV: root.tiling }
    }

    // каркас поверх - средствами отладчика сцены
    Binding { target: view.environment; property: "debugSettings"; value: dbg; when: root.wire }
    DebugSettings { id: dbg; wireframeEnabled: true }

    OrbitCameraController {
        anchors.fill: parent
        origin: orbit
        camera: cam
        panEnabled: root.mode !== "hdri"
        automaticClipping: root.mode !== "hdri"    // камера в центре неба - иначе дальность обрежется до нуля
    }

    // колесо в режиме HDRI - поле зрения, а не приближение (камера внутри неба); слой поверх
    // контроллера, чтобы колесо досталось ему первым, а нажатия и перетаскивание прошли вниз
    Item {
        anchors.fill: parent
        enabled: root.mode === "hdri"
        WheelHandler {
            onWheel: (e) => { cam.fieldOfView = Math.max(25, Math.min(110, cam.fieldOfView - e.angleDelta.y / 40)) }
        }
    }

    // одна карта текстуры плиткой или развёртка HDRI - поверх сцены
    Rectangle {
        anchors.fill: parent
        visible: root.flat != ""
        color: root.back
        Image {
            id: flatImg
            anchors.fill: parent
            anchors.margins: root.flatTile ? 0 : 16
            source: root.flat
            asynchronous: true
            fillMode: root.flatTile ? Image.Tile : Image.PreserveAspectFit
            sourceSize.width: root.flatTile ? 512 : 0
            smooth: true
        }
        Rectangle {
            anchors { left: parent.left; top: parent.top; margins: 12 }
            radius: 10; color: "#cc0d0d13"
            width: flatLbl.implicitWidth + 24; height: flatLbl.implicitHeight + 12
            Text { id: flatLbl; anchors.centerIn: parent; text: root.flatTitle; color: "#eceaf6"; font.pixelSize: 13 }
        }
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.NoButton }
    }

    // пока грузится или если не открылось
    Rectangle {
        anchors.centerIn: parent
        visible: busy.text !== ""
        radius: 12; color: "#cc14141c"; border.color: "#343448"
        width: busy.implicitWidth + 36; height: busy.implicitHeight + 22
        Text {
            id: busy
            anchors.centerIn: parent
            text: root.status !== "" ? root.status
                : (root.mode === "model" && root.modelSource != "" && loader.status !== RuntimeLoader.Success
                   && loader.status !== RuntimeLoader.Error) ? "Загружаю модель..." : ""
            color: "#c9c4dc"; font.pixelSize: 15
        }
    }
}
