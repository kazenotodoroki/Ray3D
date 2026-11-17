"""Scène d'exemple : salle esquissée, scène, gradins extrudés, line arrays L/R en miroir,
front fills et delays bi-pavillon."""
from .model import Scene, Shape, Group, LineArray, Row, Speaker, Listener, GROUP_COLORS
from .library import default_models
from .acoustics import optimize_array


def stairs_profile(x0, depth, rise, n):
    """Profil XZ de gradins : n marches."""
    x1 = x0 + n * depth
    H = n * rise
    pts = [[x0, 0], [x1, 0], [x1, H]]
    for i in range(n - 1, 0, -1):
        pts.append([x0 + i * depth, (i + 1) * rise])
        pts.append([x0 + i * depth, i * rise])
    pts.append([x0, rise])
    return pts


def default_scene() -> Scene:
    sc = Scene()
    sc.models = default_models()
    room = Shape("Salle", "Pièce", profile=[[0, 3], [4, 0], [30, 0], [30, 22], [4, 22], [0, 19]],
                 plane="XY", height=12, absorption=0.15, audience=True)
    room.recenter()
    sc.shapes = [
        room,
        Shape("Scène", "Objet", profile=[[-15, -8], [-11, -8], [-11, 8], [-15, 8]], plane="XY",
              height=1.2, absorption=0.1),
        Shape("Gradins", "Objet", profile=stairs_profile(5, 0.9, 0.4, 11), plane="XZ", height=20,
              symmetric=True, absorption=0.4, audience=True),
    ]
    main = Group("Main", GROUP_COLORS[0], main=True)
    ff = Group("Front fill", GROUP_COLORS[2])
    dl = Group("Delay", GROUP_COLORS[3])
    sc.groups = [main, ff, dl]
    st = sc.settings
    st.opt_near, st.opt_far, st.opt_znear, st.opt_zfar = 4.0, 26.0, 1.2, 5.6
    la = LineArray("Main L", main.id, "la12", x=-11.2, y=-7.5, z=9.0, n=10)
    sc.objects = [la]
    optimize_array(la, sc.model("la12"), st.opt_near, st.opt_far, st.opt_znear, st.opt_zfar,
                   st.opt_max, st.opt_step, st.opt_weight)
    sc.make_mirror(la, "Y")
    sc.objects.append(Row("Front fill", ff.id, "ff5", x=-11.15, y=-6, z=1.36, el=-8, n=4, spacing=4,
                          row_angle=90))
    dlL = Speaker("Delay L", dl.id, "bh15", x=2.0, y=-6.0, z=7.0, el=-12)
    sc.objects.append(dlL)
    sc.make_mirror(dlL, "Y")
    ctr = Group("Centre", GROUP_COLORS[4])
    sc.groups.append(ctr)
    # 2 × A15 Focus en line array horizontal (boîtes couchées), centrés au-dessus de la scène
    sc.objects.append(LineArray("Centre A15", ctr.id, "lac_a15f", x=-11.4, y=0.43, z=6.5, n=2, splays=[10.0],
                                orient="Couchée →", tilt=-25, top_angle=5.0, gain=-16.0))
    sc.listeners = [Listener("Écoute 1", -2, 0, 1.2), Listener("Écoute 2", 10, 0, 3.6)]
    st.refl_listener = sc.listeners[0].id
    sc.sync()
    return sc


def studio_scene() -> Scene:
    """Petit studio : pièce 5 × 3.8 × 2.7 m, paire de Yamaha HS8 en triangle équilatéral de 1.4 m."""
    sc = Scene()
    sc.models = default_models()
    room = Shape("Studio", "Pièce", profile=[[0, 0], [5.0, 0], [5.0, 3.8], [0, 3.8]], plane="XY", height=2.7,
                 absorption=0.12, audience=True)
    room.recenter()
    sc.shapes = [room]
    mon = Group("Monitors", GROUP_COLORS[0], main=True)
    sc.groups = [mon]
    ear = 1.2
    side = 1.4
    xs = -1.75                                   # face avant des enceintes (mur avant en x = -2.5)
    hsL = Speaker("HS8 L", mon.id, "yam_hs8", x=xs, y=-side / 2, z=ear + 0.085, az=30.0, el=0.0)
    sc.objects = [hsL]
    sc.make_mirror(hsL, "Y")
    lx = xs + side * 3 ** 0.5 / 2
    sc.listeners = [Listener("Écoute", round(lx, 3), 0.0, ear)]
    st = sc.settings
    st.refl_listener = st.sbir_listener = sc.listeners[0].id
    st.freq, st.band, st.ear, st.dyn = 250.0, "1/3 oct", ear, 15.0
    st.cov_range, st.show_rays = 3.0, False
    sc.sync()
    return sc
