# Ray 3D

Logiciel de visualisation 3D de la projection de haut-parleurs, inspiré d'[AMray](https://amcoustics.com/tools/amray).
On dessine la salle, on place des enceintes, des line arrays ou des rangées de front fills, et
l'application affiche les cônes de couverture, les rayons et leurs réflexions, une carte de niveau
sonore (SPL) et calcule les délais à appliquer à chaque groupe.

Interface sombre et minimaliste, en Python (PySide6 + pyqtgraph / OpenGL).

## Installation

Python 3.10 ou plus récent.

```
pip install -r requirements.txt
python run.py              # fenêtre de démarrage : restaurer, ouvrir ou nouvelle session
python run.py scene.json   # ouvrir une scène enregistrée
```

`h5py` n'est utile que pour importer des directivités SOFA.

## Fonctionnalités

- **Trois vues** : 3D, dessus (XY) et côté (XZ, coupe). Chaque vue passe en plein écran (⤢ ou
  double-clic sur son titre, Échap pour revenir). F11 met la fenêtre en plein écran.
- **Balade en 3D** : bouton « Balade », puis ZQSD / WASD ou flèches, E / C pour monter et descendre,
  Maj pour courir, glisser pour regarder. « À l'écouteur » place la caméra à un point d'écoute.
  « Orbite écouteur » ancre la rotation de la caméra sur l'écouteur sélectionné (ou le premier) :
  on tourne et on zoome autour de lui, et l'ancre suit l'écouteur s'il bouge.
- **Écouteur avec tête** : case « Sphère de tête » dans les propriétés d'un point d'écoute
  (diamètre 18 cm par défaut, réglable).
- **Vue de l'extérieur** : depuis l'extérieur de la pièce, les murs côté caméra s'effacent et
  l'intérieur reste visible (enceintes, objets, carte SPL).
- **Salles et objets dessinés** : esquisse avec cotes, puis extrusion (voir plus bas).
- **Enceintes** : modèles avec profil extrudé, point d'accroche, arêtes d'accroche et plusieurs
  sources (tweeter, woofer, pavillons…) chacune avec sa position, son orientation et sa directivité.
- **Line arrays** réalistes : les boîtes s'articulent sur leurs arêtes d'accroche, sans se rentrer
  dedans ; optimisation automatique des angles ; disposition verticale, couchée ou côte à côte.
- **Rangées** (front fills, sources distribuées) avec calcul de l'espacement idéal.
- **Groupes**, **miroir X / Y lié** (une modification d'un côté est recopiée de l'autre) et
  **verrou** de position (HP, formes, ensembles, écouteurs).
- **Objets composés** (bureau, régie…) : ensembles de formes, **accrochage coin sur coin** et le long
  d'une arête, **décalage** d'une sélection multiple, **sauvegarde des ensembles** pour les réutiliser.
- **Rayons et réflexions** : lancer de rayons coloré par ordre de réflexion, et chemins exacts vers
  un point d'écoute (méthode des sources images) avec retard et niveau. Option « Seulement ceux qui
  atteignent l'écouteur » : ne garde que les rayons qui passent dans la sphère de tête (ou à moins du
  rayon de capture), coupés à l'écouteur ; augmentez alors le nombre de rayons.
- **Carte SPL** sur les zones public et en coupe verticale, avec ou sans délais, à une fréquence,
  par bande ou en énergie ; pour toutes les sources ou seulement le HP / groupe sélectionné.
- **Délais** : la température donne la vitesse du son ; on choisit le ou les groupes main, les autres
  reçoivent leur délai.
- **SBIR (conception de studio)** : réponse en fréquence au point d'écoute avec les réflexions des
  parois proches (ordres 1 à 4), réflexions arrières en option, et recherche de la meilleure
  distance au mur.
- **Traitement acoustique** : zones minimales de premières réflexions sur les murs, le sol et le
  plafond (hors bass traps), pose optimisée de panneaux de la taille choisie.
- **Exports PDF** : analyse acoustique (vue 3D cadrée, SBIR, plan coté, élévations, liste des
  panneaux) et plans de découpe d'un ensemble (bureau…), cotes en mm, cm ou m.
- **Télémètre + smartphone** : mesures au télémètre (trilatération depuis 3 repères) saisies sur
  l'ordinateur ou sur un téléphone Android connecté au serveur intégré ; création de la pièce, d'objets,
  placement des enceintes et de l'écoute.
- **Annuler / Rétablir** (Ctrl+Z / Ctrl+Y), **sauvegarde automatique** à côté du fichier et
  **versions** horodatées.

## Repère et unités

X = profondeur (scène → fond), Y = largeur, Z = hauteur, en mètres.
Azimut 0° = vers +X, 90° = vers +Y. Site négatif = vers le bas. Les nombres s'écrivent avec un point.

## Formes : esquisse puis extrusion

`+ Pièce`, `+ Objet` et `+ Surface` ouvrent l'éditeur d'esquisse (le même sert aux profils
d'enceintes dans la bibliothèque) :

- clic dans le vide : ajoute un point juste après le point sélectionné (ou à la fin), aimanté à la
  grille et à 15° (Maj pour placer librement) ;
- clic sur un point : le sélectionne (bleu, et sa ligne dans le tableau) ; glisser : le déplace ;
- **Suppr** (dans le dessin ou le tableau) ou le bouton « Supprimer le point » : supprime le point
  sélectionné, quel qu'il soit ; « Insérer un point » en ajoute un au milieu du segment suivant ;
- **arcs** : glisser la petite poignée ronde au milieu d'un segment pour le courber, ou saisir sa
  **flèche** ou son **rayon** dans le tableau (flèche > 0 = arc bombé vers l'extérieur, < 0 = vers
  l'intérieur, 0 = segment droit) ; le clic droit propose aussi « segment droit » et « demi-cercle » ;
- **Ctrl+Z / Ctrl+Y** (ou boutons Annuler / Rétablir) dans l'esquisse ;
- le clic droit ouvre un menu (il ne supprime plus rien directement) ;
- le tableau donne les coordonnées et la cote de chaque segment : modifier une longueur ou un angle
  décale toute la suite du tracé ;
- choix du plan (XY dessus, XZ profil, YZ face), de la hauteur d'extrusion, extrusion symétrique ;
- préréglages rectangle et gradins.

Une pièce est automatiquement centrée sur l'origine, sol à z = 0. Double-clic sur une forme dans
l'arbre pour la rééditer.

Dans les champs numériques, on tape directement la valeur (un clic sélectionne tout) puis Entrée ou
Tab pour valider ; la virgule est acceptée. Flèches haut / bas ou molette (champ actif) : ± un pas,
Maj × 10, Ctrl ÷ 10. Échap annule la saisie en cours. La carte SPL se calcule sur le sol d'une pièce et sur les faces
supérieures d'un objet (marches de gradins) marqués « Zone public ».

## Sélection, déplacements et objets composés

**Sélection multiple** : Ctrl+clic ou Maj+clic dans l'arbre. Les actions Décaler, Verrou, Dupliquer,
Supprimer et Enregistrer comme ensemble s'appliquent à toute la sélection.

**Coins** : l'élément sélectionné (forme, ensemble ou HP) affiche ses coins numérotés dans les vues,
et leurs coordonnées dans le tableau « Coins » des propriétés (Ctrl+C pour copier).

**Décaler…** (Ctrl+M) : déplace toute la sélection de dX, dY, dZ. Option « Déplacer une copie ».
Les éléments verrouillés ne bougent pas. Un HP lié en miroir entraîne son partenaire en symétrie.

**Accrocher…** (Ctrl+K) : pose un coin de l'élément sélectionné sur un coin d'un autre élément
(ou sur un point libre), puis le fait glisser le long d'une arête partant de ce coin, d'une distance
donnée (boutons Début / Milieu / Fin), avec un décalage supplémentaire si besoin. Les vues montrent
le résultat en direct ; Annuler remet tout en place.

Exemple, un bureau : `+ Objet` pour le plateau et chaque pied, puis Accrocher le coin bas du plateau
sur le coin haut d'un pied ; Accrocher le second pied sous l'autre bout du plateau en glissant le
long de l'arête.

**Ensembles** (menu « Ensembles ») :

- *Créer un ensemble avec la sélection* (Ctrl+G) : regroupe des formes en un objet composé, qui se
  sélectionne, se déplace, s'accroche et se verrouille d'un bloc. Glisser une forme sur un ensemble
  dans l'arbre l'y ajoute ; la glisser sur « FORMES » l'en retire.
- **Sous-ensembles** : un ensemble peut contenir d'autres ensembles (par exemple « Bureau » qui
  contient « Supports »). Ctrl+G sur des ensembles sélectionnés les range dans un nouvel ensemble ;
  glisser un ensemble sur un autre dans l'arbre l'y range, le glisser sur « FORMES » le remet au
  premier niveau. Déplacer ou verrouiller un ensemble agit sur tout son contenu.
- *Dissocier* (Ctrl+Maj+G) : le contenu remonte d'un niveau.
- *Enregistrer la sélection comme ensemble…* : fichier `.r3dset` (par défaut dans
  `~/.ray3d/ensembles/`), qui peut contenir des formes, des ensembles, des HP (avec leurs modèles) et
  des écouteurs.
- *Insérer un ensemble…* : l'ajoute à la scène à ses coordonnées d'origine, prêt à être placé avec
  Accrocher ou Décaler.

**Verrou** (Ctrl+L) : HP, formes, ensembles et écouteurs. Un élément verrouillé ne se déplace ni à la
souris, ni par Décaler / Accrocher, et ses champs de position sont grisés.

## Haut-parleurs

### Bibliothèque HP

Chaque modèle comprend :

- un **profil latéral** (f avant, u haut) extrudé sur la largeur de l'enceinte ;
- une **origine (0, 0) = point d'accroche** de l'enceinte ;
- une **arête d'accroche haute** et une **arête d'accroche basse** pour le chaînage en line array ;
- un ou plusieurs **éléments sonores** : position, azimut, site, directivité (pavillon avec
  ouvertures H / V, omni, cardioïde, super / hypercardioïde ou mesurée), niveau à 1 m, délai.

Une petite vue 3D montre le volume, l'accroche, les arêtes et chaque source avec son axe et son
cône −6 dB, pour vérifier qu'elles sont au bon endroit.

### Placement

- `+ HP` : une enceinte. `+ Line array` : n boîtes. `+ Rangée` : enceintes régulièrement espacées.
- Line array : l'arête haute d'une boîte vient sur l'arête basse de la précédente et le splay est
  une rotation autour de cette arête. La plage de splay sans collision est calculée à partir du
  profil ; un splay hors limite est signalé en rouge.
- Disposition : **verticale**, **couchée ← / →** (boîtes tournées de 90°, chaînées à l'horizontale,
  par ex. 2 × A15) ou **côte à côte ← / →** (boîtes debout, articulées sur leurs arêtes arrière).
- `+ Groupe`, puis glisser un objet sur un groupe dans l'arbre (ou clic droit → Déplacer).
- `Miroir X` / `Miroir Y` : copie liée par rapport au plan X = 0 / Y = 0. « Délier » casse le lien.
- `🔒 Verrou` (Ctrl+L) : bloque la position et l'orientation (objet, groupe et son miroir).

### Modèles fournis

| Modèle | Remarques |
|---|---|
| LA12, PS12, BH15 (bi-pavillon), FF5, SB18 | Modèles génériques |
| L-Acoustics X12, SB28, A15 Focus, A15 Wide | Dimensions et niveaux max des fiches ; géométrie interne et directivité approchées |
| Yamaha HS8 | 250 × 390 × 334 mm, woofer 8" + dôme 1", filtre 2 kHz, 47 Hz – 24 kHz (−3 dB) |
| Yamaha HS8S | Caisson 300 × 350 × 389 mm, 8", 22 – 160 Hz (−10 dB) |

Pour les HS8 et HS8S, Yamaha ne publie ni niveau maximum ni dispersion : les niveaux, ouvertures et
positions des haut-parleurs sur la façade sont estimés. Remplacez-les par des mesures si vous en
avez. Les cotes du SB28 sont à vérifier sur la fiche L-Acoustics.

### Import de directivités et de modèles

Dans la bibliothèque, « Importer une directivité… » sur l'élément sélectionné :

- **Polaires H / V en texte** (.txt, .csv) : sections `[H]` et `[V]`, ligne `angle, f1, f2, …`, puis
  une ligne par angle en dB. Voir `exemples/polaires_exemple.txt`. Une seule section = même polaire
  en H et en V.
- **SOFA / AES69** (.sofa, conventions FreeFieldDirectivityTF ou GeneralTF), ramené en bandes
  d'octave (nécessite `h5py`).
- **Modèle Ray 3D** (.r3dspk) : export / import d'un modèle complet (profil, arêtes, éléments, mesures).

Les formats GLL et XHN (EASE) et CF1 / CF2 (CLF) sont fermés : il faut les exporter en polaires
texte ou en SOFA depuis l'outil du fabricant.

## SBIR (conception de studio)

Bouton **Exemple studio** : pièce de 5 × 3.8 × 2.7 m, paire de Yamaha HS8 en triangle équilatéral
de 1.4 m, point d'écoute à 1.2 m.

L'onglet **SBIR** calcule la réponse en fréquence au point d'écoute : somme complexe (amplitude et
phase) du son direct et des réflexions sur les parois, par la méthode des sources images
(ordre 1 à 4). Il affiche :

- la courbe totale et celle du son direct seul (lissage au choix, de 1/48 à 1/3 d'octave) ;
- le premier creux de chaque paroi en trait pointillé, à la couleur de la paroi ;
- un tableau des réflexions : paroi, différence de trajet, retard, premier creux c / (2·Δ),
  niveau relatif à la fréquence du creux ;
- les chemins de réflexion dans les vues 2D et 3D, colorés par paroi : la couleur d'une réflexion
  d'ordre 2 à 4 est celle de la première paroi touchée, et le tableau donne la chaîne des parois
  (« 2× · Mur avant → Plafond ») ; plus l'ordre est élevé, plus le trait est transparent.

Ordres 3 et 4 : les chemins sont cherchés par lancer de rayons puis validés exactement par sources
images (environ 1 à 2 s à l'ordre 4 pour un studio). Les balayages restent limités à l'ordre 2.

**Exporter l'analyse en PDF** (bouton sous le tableau) : voir « Exports PDF ».

Parois prises en compte, chacune activable : mur derrière l'enceinte, murs latéraux, sol, plafond.

**Réflexions arrières (en option)** :

- *Rayonnement arrière des enceintes* : dans le grave, une enceinte rayonne presque autant vers
  l'arrière que vers l'avant ; c'est ce son qui revient du mur derrière elle (le SBIR classique).
  La directivité passe d'omni à celle du modèle autour de c / (π · largeur de la face avant).
- *Mur derrière la position d'écoute*.

Les sources sont l'enceinte ou le groupe sélectionné (ou toutes les sources).

**Optimisation** : on choisit une bande (40–300 Hz par défaut) et on balaye :

- la distance entre la face avant de l'enceinte sélectionnée et le mur derrière elle ;
- ou la position d'écoute le long de X ou de Y.

Le critère est l'écart-type de la réponse lissée dans la bande. « Appliquer la meilleure position »
déplace l'enceinte le long de son axe (son miroir lié suit) ou le point d'écoute. Une enceinte
verrouillée n'est pas déplacée.

Limites : parois planes et réflexions spéculaires, absorption indépendante de la fréquence, pas de
modes de la pièce au-delà de ce que donnent les sources images d'ordre 4, pas de coupure dans le
grave des enceintes.

## Traitement acoustique (hors bass traps)

Onglet **TRAITEMENT**. Pour chaque paroi de la pièce (murs, sol, plafond), Ray 3D cherche les points
de réflexion du premier ordre entre les enceintes et une **zone d'écoute** autour de la tête
(largeur, profondeur, hauteur réglables, 0.60 × 0.30 × 0.20 m par défaut). Le rectangle qui les
englobe, plus une marge, est la **zone minimale** à traiter. Les réflexions masquées (par le bureau
par exemple) ne comptent pas.

- Les zones s'affichent **en gras** (jaune) dans les vues, avec leurs dimensions ; le tableau donne
  dimensions et position (mur : depuis le coin gauche vu de l'intérieur et depuis le sol ; sol /
  plafond : en X / Y).
- **Masquer les zones minimales** (case dans les onglets SBIR et TRAITEMENT), par exemple une fois
  les panneaux posés.
- Le **sol** n'est pas traité par défaut : sélectionnez sa zone et cochez « Traiter cette zone ».
- **Plafond suspendu** : « Suspension sous plafond » donne la distance entre le plafond et le dessus
  des panneaux du plafond (réglage par défaut dans « Pose », puis par zone).
- Pour chaque zone : traiter ou non, **taille de panneau** (120 × 60, 60 × 60, 120 × 30, 100 × 50,
  60 × 30 cm, sur mesure, ou un seul panneau de la taille de la zone, par défaut pour le sol),
  orientation (auto / portrait / paysage), épaisseur.
- **Poser les panneaux** : grille centrée sur la zone, dans l'orientation qui couvre la zone avec le
  moins de panneaux, sans sortir de la paroi. Les panneaux sont des objets rangés dans l'ensemble
  « Traitement acoustique » (un sous-ensemble par paroi) et absorbent dans les calculs (SBIR,
  réflexions). « Retirer les panneaux » les supprime ; poser à nouveau les remplace.
- Noms des parois : mur avant (derrière les enceintes), arrière, gauche et droit vus depuis l'écoute.

**Bass traps** : choisissez un angle de la pièce (avant / arrière, gauche / droit vu depuis
l'écoute), une forme (triangle, arrondi ou carré d'angle), le côté le long des murs et la hauteur
(0 = du sol au plafond), puis « Ajouter le bass trap ». C'est une forme ordinaire : « Éditer
l'esquisse » permet de la redessiner à la main. Toute forme peut aussi devenir un bass trap avec la
case « Bass trap » de ses propriétés. Les bass traps sont rangés dans « Traitement acoustique ›
Bass traps », restent en place quand on pose ou retire les panneaux, absorbent dans les calculs et
apparaissent dans le PDF (plan hachuré, tableau). Leur emplacement n'est pas calculé : c'est à vous
de les concevoir.

## Exports PDF

Unités des plans au choix dans l'onglet TRAITEMENT : **mm** (par défaut), cm ou m.

**Analyse acoustique** (onglets SBIR ou TRAITEMENT) : une fenêtre 3D s'ouvre d'abord pour cadrer la
vue qui sera mise dans le rapport. Le PDF (A4 paysage) contient :

1. synthèse : vue 3D, pièce, écoute, enceintes, zones minimales ;
2. courbe SBIR et tableau des réflexions ;
3. plan coté de la pièce : murs, bureau, enceintes, écouteur, zones, panneaux et bass traps ;
4. une élévation par paroi traitée (1:20 à 1:50) : zone minimale en gras et cotée, panneaux cotés,
   suspension pour le plafond ;
5. liste des panneaux (repère, dimensions, position du coin bas gauche, suspension) et des bass traps.

Quand les panneaux d'une paroi sont posés (ou que les zones sont masquées), sa zone minimale
n'apparaît plus dans le PDF : seuls les panneaux sont dessinés et cotés.

**Plans de découpe d'un ensemble** (ex. le bureau) : choix de l'ensemble et des unités, puis

- vues de dessus, de face et de côté de l'ensemble à la même échelle, encombrement coté ;
- nomenclature : pièces identiques regroupées (repère P1, P2…, quantité, profil, épaisseur) ;
- position de chaque pièce dans l'ensemble ;
- une page par pièce : profil à l'échelle avec la longueur de chaque segment, le rayon et la corde
  des arcs, l'encombrement, les sommets numérotés (coordonnées et angles), et la vue de chant avec
  l'épaisseur (longueur d'extrusion).

## Télémètre et smartphone

Onglet **TÉLÉMÈTRE** : même méthode que l'app Régie (télémètre sans inclinomètre). On mesure les
distances d'un point à trois repères A, B, C ; Ray 3D calcule sa position en 3D (trilatération) et la
précision obtenue (± 1 cm supposé par distance).

**Repère**

- *Libre (comme Régie)* : trois points au sol A, B, C bien écartés et non alignés ; on saisit A–B,
  A–C, B–C, la hauteur de mesure (0 si le télémètre est posé sur les points), le côté de C, puis où
  se trouve A dans la scène et la direction de A→B.
- *Sur des points de la scène* : A, B, C sont des points connus (angles de la pièce au sol ou au
  plafond, écouteur, enceinte… à choisir dans la liste, ou X, Y, Z saisis). Les côtés se calculent
  seuls, et tout point mesuré depuis ces trois repères tombe directement au bon endroit : c'est la
  triangulation pour **placer une source** dans une salle déjà dessinée.

**Points** : nom, type (angle de pièce au sol / au plafond, point d'objet, enceinte, écoute, autre),
groupe (ex. « Bureau »), distances depuis A, B, C, « orienté vers » un autre point, hauteur connue
(mètre ruban, pour les points bas et loin des repères), point sous le plan de mesure. Les points
s'affichent dans les vues quand l'onglet est ouvert.

**Construire dans la scène**

- *Créer la pièce* : contour des angles au sol (ou des points sélectionnés), hauteur = angles au
  plafond mesurés, ou saisie, ou 2.50 m.
- *Créer l'objet* : contour des points d'un groupe (ou de la sélection). Épaisseur auto : du sol
  jusqu'aux points s'ils sont à la même hauteur (dessus d'un bureau), sinon de la hauteur basse à la
  haute ; ou épaisseur saisie, vers le bas depuis les points.
- *Enceinte au point* / *Écoute au point* : crée l'élément, orienté (azimut, site) vers son point
  « orienté vers ».
- *Déplacer la sélection* : amène l'enceinte ou l'écouteur sélectionné sur le point mesuré.

Tout est annulable (Ctrl+Z) et enregistré avec la scène.

### Serveur et application Android

« **Démarrer le serveur** » (port 8765) : Ray 3D devient un petit serveur sur le réseau local.
L'adresse s'affiche en grand (ex. `http://192.168.1.20:8765`).

- Sur le téléphone, même Wi-Fi : ouvrir cette adresse. La page propose de **télécharger l'application
  Android** et de l'**ouvrir dans le navigateur** (même interface, rien à installer).
- L'application (et la page) reprennent l'onglet Télémètre de Régie : repère, points, distances,
  aperçu de la position et de la précision, liste des points, et boutons « Créer la pièce »,
  « Créer l'objet », « Enceinte ici », « Écoute ici ». Chaque saisie arrive tout de suite dans
  Ray 3D ; ce qui est saisi sur l'ordinateur apparaît sur le téléphone.
- L'application trouve le serveur toute seule (diffusion UDP, port 47800), ou on saisit l'adresse.
  Elle garde l'écran allumé ; « ⇄ » ou Retour revient au choix du serveur.
- Windows demande au premier démarrage d'autoriser Python sur le réseau : acceptez pour les réseaux
  privés. Le serveur n'a pas de mot de passe : ne le démarrez que sur un réseau de confiance.

**Compiler l'APK** (dossier `android/`, une coquille WebView en Kotlin) :

- *Sans rien installer* : poussez le dépôt sur GitHub ; le workflow `.github/workflows/apk.yml`
  compile l'APK (onglet Actions › « APK télémètre » › artefact `ray3d-telemetre-apk`).
- *Android Studio* : File › Open › `android/`, puis Build › Build APK(s).

Puis, dans l'onglet TÉLÉMÈTRE : « **Choisir l'APK Android…** » (copié dans
`~/.ray3d/ray3d-telemetre.apk`) ; le serveur le propose alors au téléchargement. Un APK posé dans
`android/ray3d-telemetre.apk` est servi aussi. Sur le téléphone : autoriser l'installation depuis le
navigateur, puis ouvrir le fichier.

## Délais

Onglet DÉLAIS : température, groupe(s) main, point de référence (impact de l'axe de chaque source
ou point d'écoute) et décalage de Haas. Délai = (distance au main − distance à la source) / c + Haas.
Un délai négatif (source plus loin que le main) est signalé.

## Fichiers

- Scènes : `.json` (Ctrl+S / Ctrl+O). Les scènes de la toute première version ne sont pas compatibles.
  Le titre de la fenêtre montre le fichier, précédé de « • » s'il y a des modifications non
  enregistrées.

### Sauvegarde automatique et versions

- **Toutes les 20 s** (si la scène a changé) et à la fermeture.
- **À côté du fichier ouvert** : `salle.json` → `salle.autosave.json` dans le même dossier (si le
  dossier n'est pas modifiable : `~/.ray3d/autosave/`). Une scène jamais enregistrée va dans
  `~/.ray3d/autosave.json`.
- La sauvegarde automatique **garde le chemin du fichier d'origine** : après une restauration,
  Ctrl+S réécrit au bon endroit.
- **Versions horodatées** : une copie au plus toutes les 5 minutes de travail, plus une à la fermeture
  et avant de changer de scène, dans `~/.ray3d/versions/<nom>/` (40 par scène). Bouton **Versions…**
  (2e barre) pour en rouvrir une.
- **Au démarrage**, une fenêtre propose : restaurer la session sauvegardée automatiquement, rouvrir une
  scène récente (avec ses modifications non enregistrées s'il y en a), ouvrir un fichier, ou commencer
  une **nouvelle session** (confirmation demandée ; l'ancienne session est rangée dans les versions).
- **Nouveau, Exemple studio, Ouvrir** demandent toujours confirmation avant de changer de session ;
  s'il y a des modifications non enregistrées : « Enregistrer d'abord », « Continuer sans
  enregistrer » ou « Annuler ».
- En ouvrant un fichier dont la sauvegarde automatique est plus récente, Ray 3D propose de la
  restaurer.

## Structure du code

```
run.py              lancement
ray3d/
  app.py            fenêtre principale, actions, annuler, sauvegarde auto
  model.py          scène, formes, modèles de HP, objets, groupes, miroir
  geometry.py       polygones, triangulation, extrusion
  acoustics.py      directivité, rayons, réflexions, SPL, délais, optimiseur
  views.py          vues 3D et 2D
  panels.py         propriétés et onglets
  sketch.py         éditeur d'esquisse
  libdialog.py      bibliothèque HP et aperçu 3D
  library.py        modèles fournis
  importers.py      import polaires / SOFA / modèles
  sbir.py           calcul SBIR, classement des parois, balayages
  sbirtab.py        onglet SBIR
  paths.py          chemins spéculaires exacts jusqu'à l'ordre 4
  treatment.py      zones de premières réflexions, pose des panneaux
  treattab.py       onglet TRAITEMENT
  pdfdoc.py         mise en page PDF, dessin à l'échelle, cotes
  report.py         exports PDF (analyse acoustique, plans de découpe)
  sessions.py       sauvegarde automatique, versions, fenêtre de démarrage
  telemetry.py      trilatération, repère, construction pièce / objet / sources
  teleserver.py     serveur HTTP + découverte UDP pour le smartphone
  teletab.py        onglet TÉLÉMÈTRE
  web/              page mobile du télémètre
android/            application Android (WebView) du télémètre
  edit.py           coins, déplacements, verrous, ensembles et leur sauvegarde
  tools.py          dialogues Décaler et Accrocher
  widgets.py        champs numériques
  demo.py           scènes d'exemple (salle, studio)
  style.py          thème
exemples/           fichier de polaires d'exemple
```

## Limites du modèle

Directivités idéalisées pour les modèles fournis, réflexions spéculaires uniquement, carte SPL
sans masquage par les obstacles ni absorption de l'air. Outil d'aide au placement, pas un
remplacement des logiciels de prédiction des fabricants.
