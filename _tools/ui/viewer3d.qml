// Просмотр ассетов Unreal: модель (FBX через assimp), текстура на фигуре, HDRI-панорама изнутри.
// Свойства ставит ui/viewer3d.py; мышь: тянуть - вращать, колесо - ближе/дальше, правая - сдвиг.
// Модель и фигура стоят на полу (y = 0), камера крутится вокруг их середины.
import QtQuick
import QtQuick3D
import QtQuick3D.Helpers
import QtQuick3D.AssetUtils
import QtQuick.Shapes

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
    property real modelYaw: 0              // модель стоит спиной - развернуть (градусы, из _unreal_yaw.json)
    property bool linearColors: false     // цвета материалов в файле линейные (Quaternius) - на экран через гамму
    property bool tryOn: false            // примерка: материал текстуры (texMat) на детали модели
    property var parts: []                // детали = разные материалы модели: [{name, count}] - для списка в окне
    property var partMats: []             // сами материалы деталей (тот же порядок)
    property var tryMask: []              // номера деталей, на которые надеть; пусто - на все
    property int flashPart: -1            // подсветить деталь (наведение на строку списка)
    property color tint: "white"          // оттенок примеряемой текстуры
    property real uvRotation: 0           // поворот рисунка, градусы
    property real roughAmount: 1.0        // шероховатость: 1 - как в карте, меньше - глянцевее
    property bool smooth: true            // камера перелетает к новому кадру, модель проявляется (настройки: анимации)
    property var origMats: []             // [{model, mats}] - вернуть родные материалы
    property real humanHeight: 0          // силуэт человека 180 см в масштабе модели (единицы сцены), 0 - нет
    property bool showHuman: false
    property real width3d: 200             // ширина модели на сцене - человек встаёт сбоку
    property string title: ""              // подпись поверх сцены (большое окно)
    property string subtitle: ""
    property bool brightened: false        // линейные цвета уже переведены (один раз на загрузку)
    property bool fitted: false           // подгонка под кадр - один раз на загрузку: смена масштаба
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

    // в FBX без шероховатости assimp ставит 0 - зеркало: на ярком небе модель белёсая, в бликах
    // (персонажи Kenney). Unreal в таком случае берёт 0.5 - здесь так же; стекло (прозрачное) не трогаем
    function matte(n) {
        var kids = n.children || []
        for (var i = 0; i < kids.length; i++) {
            var c = kids[i]
            if (c.materials !== undefined) {
                for (var j = 0; j < c.materials.length; j++) {
                    var m = c.materials[j]
                    if (m && m.roughness !== undefined && m.roughness < 0.05 && m.metalness < 0.5
                            && m.opacity >= 0.99 && !m.roughnessMap) {
                        m.roughness = 0.7
                        m.specularAmount = 0.25
                    }
                }
            }
            if (c.mapPositionToScene !== undefined) matte(c)
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

    // детали - уникальные материалы модели (у дивана: ткань, дерево ножек, металл)
    function collectParts() {
        restoreMats()
        var ms = models(loader, []), mats = [], info = []
        for (var i = 0; i < ms.length; i++) {
            for (var j = 0; j < ms[i].materials.length; j++) {
                var m = ms[i].materials[j], k = mats.indexOf(m)
                if (k < 0) {
                    mats.push(m)
                    // имя: материала, иначе меша (у FBX Poly Haven материалы часто без имени)
                    info.push({name: m.objectName || ms[i].objectName || ("Деталь " + mats.length), count: 1})
                } else info[k].count += 1
            }
        }
        partMats = mats
        parts = info
    }

    function applyTryOn() {
        restoreMats()
        var on = tryOn || flashPart >= 0
        if (!on || mode !== "model" || loader.status !== RuntimeLoader.Success) return
        var saved = []
        var ms = models(loader, [])
        for (var i = 0; i < ms.length; i++) {
            var keep = [], now = []
            for (var j = 0; j < ms[i].materials.length; j++) {
                var orig = ms[i].materials[j], k = partMats.indexOf(orig)
                keep.push(orig)
                var wear = tryOn && (tryMask.length === 0 || tryMask.indexOf(k) >= 0)
                now.push(k >= 0 && k === flashPart ? flashMat : (wear ? texMat : orig))
            }
            saved.push({model: ms[i], mats: keep})
            ms[i].materials = now
        }
        origMats = saved
    }

    function restoreMats() {
        for (var i = 0; i < origMats.length; i++) origMats[i].model.materials = origMats[i].mats
        origMats = []
    }

    onTryOnChanged: applyTryOn()
    onTryMaskChanged: applyTryOn()
    onFlashPartChanged: applyTryOn()

    function fit() {
        if (fitted || mode !== "model" || loader.status !== RuntimeLoader.Success) return
        fitted = true
        if (linearColors && !brightened) { brighten(loader); brightened = true }  // подгонка бывает повторной
        matte(loader)
        collectParts()
        if (tryOn) applyTryOn()
        turn.eulerRotation = Qt.vector3d(0, modelYaw, 0)
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
        width3d = Math.max(dx, dz) * s
        sizeText = [dx, dy, dz].map(function (v) { return v < 10 ? v.toFixed(2) : Math.round(v) }).join(" x ")
        resetView()
        if (smooth) appear.restart()  // загруженная модель проявляется и чуть «встаёт» на подиум
    }

    function resetView() {
        var h = mode === "tex" ? (shape === "plane" ? 0 : 180) : mode === "hdri" ? 0 : height3d
        var human = mode === "model" && showHuman && humanHeight > 0
        if (human) h = Math.max(h, humanHeight)
        var pos = Qt.vector3d(human ? -humanHeight * 0.2 : 0, h / 2, 0)
        var rot = mode === "hdri" ? Qt.vector3d(0, 0, 0)
                : mode === "tex" && shape === "plane" ? Qt.vector3d(-55, 20, 0) : Qt.vector3d(-16, 32, 0)
        // узкое высокое окно (панель вкладки) - камера дальше, иначе предмет обрезан по бокам
        var aspect = view.width > 0 ? view.height / view.width : 1
        var far = human ? Math.max(1, h / 200, (width3d / 2 + humanHeight * 0.6) / 140) : 1
        var camPos = Qt.vector3d(0, 0, mode === "hdri" ? 0.01 : 420 * camScale * far * Math.max(1, aspect * 1.05))
        cam.fieldOfView = mode === "hdri" ? 75 : 40
        if (mode === "hdri") { cam.clipNear = 0.01; cam.clipFar = 1000 }
        fly.stop()
        if (!smooth || mode === "hdri" || plain) {
            orbit.position = pos; orbit.eulerRotation = rot; cam.position = camPos
            return
        }
        // перелёт: по кругу - коротким путём (после вращения мышью угол бывает 400 и больше)
        var cur = orbit.eulerRotation
        var dy = (((rot.y - cur.y) % 360) + 540) % 360 - 180
        flyPos.from = orbit.position; flyPos.to = pos
        flyRot.from = cur; flyRot.to = Qt.vector3d(rot.x, cur.y + dy, rot.z)
        flyCam.from = cam.position; flyCam.to = camPos
        fly.start()
    }

    ParallelAnimation {
        id: fly
        Vector3dAnimation { id: flyPos; target: orbit; property: "position"; duration: 560; easing.type: Easing.OutCubic }
        Vector3dAnimation { id: flyRot; target: orbit; property: "eulerRotation"; duration: 560; easing.type: Easing.OutCubic }
        Vector3dAnimation { id: flyCam; target: cam; property: "position"; duration: 560; easing.type: Easing.OutCubic }
    }
    ParallelAnimation {
        id: appear
        NumberAnimation { target: turn; property: "opacity"; from: 0; to: 1; duration: 420; easing.type: Easing.OutCubic }
        Vector3dAnimation { target: turn; property: "scale"; from: Qt.vector3d(0.9, 0.9, 0.9); to: Qt.vector3d(1, 1, 1); duration: 520; easing.type: Easing.OutBack }
    }

    onModelSourceChanged: { fitted = false; brightened = false; origMats = [] }
    onModeChanged: { if (mode !== "model") height3d = 200; resetView() }
    onShapeChanged: resetView()
    onShowHumanChanged: resetView()

    // фон: глубокий градиент, мягкое пятно света за моделью в цвет акцента и виньетка по краям
    Rectangle {
        anchors.fill: parent
        visible: !root.plain
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.lighter(root.back, 1.55) }
            GradientStop { position: 0.62; color: root.back }
            GradientStop { position: 1.0; color: Qt.darker(root.back, 1.35) }
        }
    }
    Shape {
        anchors.fill: parent
        visible: !root.plain
        ShapePath {
            strokeWidth: 0
            strokeColor: "transparent"
            fillGradient: RadialGradient {
                centerX: root.width / 2; centerY: root.height * 0.42
                centerRadius: Math.max(root.width, root.height) * 0.55
                focalX: centerX; focalY: centerY
                GradientStop { position: 0.0; color: Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.16) }
                GradientStop { position: 0.5; color: Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.05) }
                GradientStop { position: 1.0; color: "transparent" }
            }
            PathRectangle { x: 0; y: 0; width: root.width; height: root.height }
        }
    }
    Shape {
        anchors.fill: parent
        visible: !root.plain
        ShapePath {
            strokeWidth: 0
            strokeColor: "transparent"
            fillGradient: RadialGradient {
                centerX: root.width / 2; centerY: root.height / 2
                centerRadius: Math.hypot(root.width, root.height) * 0.62
                focalX: centerX; focalY: centerY
                GradientStop { position: 0.55; color: "transparent" }
                GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.45) }
            }
            PathRectangle { x: 0; y: 0; width: root.width; height: root.height }
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
                id: cam; objectName: "cam"; position: Qt.vector3d(0, 0, 420); clipNear: 1; clipFar: 20000
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
        // подиум: низкий диск под моделью и светящийся край в цвет акцента
        Node {
            visible: root.floor && root.mode === "model"
            property real r: Math.max(1.2, root.width3d * 0.012 + 0.2)
            Model {
                source: "#Cylinder"
                position: Qt.vector3d(0, -0.5, 0)
                scale: Qt.vector3d(parent.r + 0.04, 0.012, parent.r + 0.04)
                castsShadows: false
                materials: PrincipledMaterial {
                    baseColor: root.accent
                    emissiveFactor: Qt.vector3d(root.accent.r * 0.9, root.accent.g * 0.9, root.accent.b * 0.9)
                    lighting: PrincipledMaterial.NoLighting
                }
            }
            Model {
                source: "#Cylinder"
                position: Qt.vector3d(0, -0.2, 0)
                scale: Qt.vector3d(parent.r, 0.012, parent.r)
                receivesShadows: true
                castsShadows: false
                materials: PrincipledMaterial {
                    baseColor: Qt.lighter(root.back, 1.7)
                    roughness: 0.55
                    metalness: 0.0
                }
            }
        }

        // человек 180 см для масштаба: простая фигура (единицы - сантиметры, масштаб - humanHeight / 180)
        Node {
            visible: root.showHuman && root.humanHeight > 0 && root.mode === "model"
            position: Qt.vector3d(-(root.width3d / 2 + root.humanHeight * 0.3), 0, root.width3d * 0.15)
            scale: Qt.vector3d(root.humanHeight / 180, root.humanHeight / 180, root.humanHeight / 180)
            property var mat: PrincipledMaterial {
                baseColor: Qt.rgba(root.accent.r * 0.5 + 0.35, root.accent.g * 0.5 + 0.35, root.accent.b * 0.5 + 0.35, 1)
                roughness: 0.6
                opacity: 0.72
                alphaMode: PrincipledMaterial.Blend
            }
            Model { source: "#Sphere"; position: Qt.vector3d(0, 166, 0); scale: Qt.vector3d(0.23, 0.26, 0.23); materials: parent.mat }
            Model { source: "#Cylinder"; position: Qt.vector3d(0, 148, 0); scale: Qt.vector3d(0.11, 0.1, 0.11); materials: parent.mat }
            Model { source: "#Cylinder"; position: Qt.vector3d(0, 118, 0); scale: Qt.vector3d(0.36, 0.5, 0.2); materials: parent.mat }
            Model { source: "#Cylinder"; position: Qt.vector3d(-9, 46, 0); scale: Qt.vector3d(0.13, 0.9, 0.13); materials: parent.mat }
            Model { source: "#Cylinder"; position: Qt.vector3d(9, 46, 0); scale: Qt.vector3d(0.13, 0.9, 0.13); materials: parent.mat }
            Model { source: "#Cylinder"; position: Qt.vector3d(-23, 112, 0); eulerRotation.z: -6; scale: Qt.vector3d(0.09, 0.62, 0.09); materials: parent.mat }
            Model { source: "#Cylinder"; position: Qt.vector3d(23, 112, 0); eulerRotation.z: 6; scale: Qt.vector3d(0.09, 0.62, 0.09); materials: parent.mat }
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
                    baseColor: root.baseMap != "" ? root.tint : "#999999"
                    baseColorMap: root.baseMap != "" ? tBase : null
                    normalMap: root.normalMap != "" ? tNorm : null
                    roughness: root.roughAmount
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
                PrincipledMaterial {  // подсветка детали при наведении на её строку в окне
                    id: flashMat
                    lighting: PrincipledMaterial.FragmentLighting
                    baseColor: root.accent
                    emissiveFactor: Qt.vector3d(0.35, 0.3, 0.45)
                    roughness: 0.6
                }
            }
        }
        Texture { id: tBase; rotationUV: root.uvRotation; pivotU: 0.5; pivotV: 0.5; source: root.baseMap; scaleU: root.tiling; scaleV: root.tiling; generateMipmaps: true; mipFilter: Texture.Linear }
        Texture { id: tNorm; rotationUV: root.uvRotation; pivotU: 0.5; pivotV: 0.5; source: root.normalMap; scaleU: root.tiling; scaleV: root.tiling; generateMipmaps: true; mipFilter: Texture.Linear }
        Texture { id: tRough; rotationUV: root.uvRotation; pivotU: 0.5; pivotV: 0.5; source: root.roughMap; scaleU: root.tiling; scaleV: root.tiling; generateMipmaps: true; mipFilter: Texture.Linear }
        Texture { id: tMetal; rotationUV: root.uvRotation; pivotU: 0.5; pivotV: 0.5; source: root.metalMap; scaleU: root.tiling; scaleV: root.tiling; generateMipmaps: true; mipFilter: Texture.Linear }
        Texture { id: tAo; rotationUV: root.uvRotation; pivotU: 0.5; pivotV: 0.5; source: root.aoMap; scaleU: root.tiling; scaleV: root.tiling; generateMipmaps: true; mipFilter: Texture.Linear }
        Texture { id: tHeight; rotationUV: root.uvRotation; pivotU: 0.5; pivotV: 0.5; source: root.heightMap; scaleU: root.tiling; scaleV: root.tiling }
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

    // название поверх сцены (большое окно): крупно имя, под ним вид и раздел, тонкая черта акцента
    Column {
        visible: root.title !== "" && root.flat == ""
        anchors { left: parent.left; top: parent.top; leftMargin: 22; topMargin: 18 }
        spacing: 4
        Rectangle { width: 34; height: 3; radius: 2; color: root.accent }
        Text {
            text: root.title; color: root.back.hslLightness > 0.5 ? "#1e1c28" : "#f4f2fb"; font.pixelSize: 26; font.weight: Font.DemiBold
            style: Text.Raised; styleColor: "#40000000"
        }
        Text { text: root.subtitle; color: root.back.hslLightness > 0.5 ? "#5c586e" : Qt.rgba(1, 1, 1, 0.55); font.pixelSize: 13; font.letterSpacing: 0.5 }
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
