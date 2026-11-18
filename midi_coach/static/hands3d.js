// Hands on the falling notes, in 3D (Sheet ▸ Hands on the keys). The hands are the WebXR
// "generic-hand" models (hands/left.glb, right.glb; MIT, Amazon) drawn with three.js
// (vendor/three; MIT) and posed every frame on the keys roll.js picks for each finger. The view is
// a piano video's: from above and behind the player, so you see the backs of the hands, the
// fingers curled down onto the keys and the forearms running off the bottom, with a soft shadow on
// the keys and a pressing fingertip lit in its hand's colour. roll.js draws its 2D hands instead
// when WebGL or this module can't load.
//
// World: x to the right in page pixels (as roll.js lays out the keys), y away from the player,
// z up; y = 0 is the far end of the keys. The keys are as long as a real piano's for the size of
// the hands, however short roll.js draws them: the camera looks forward and down at whatever
// tilt makes them that long on the page (steeply from above for long keys, from further behind
// the player for short ones), so anything on the keys (z = 0) lands where roll.js drew it:
// page y = floor − (y·sin tilt + z·cos tilt).
import * as THREE from 'three';
import {GLTFLoader} from './vendor/three/loaders/GLTFLoader.js';

let SIN = Math.sin(62 * Math.PI / 180), COS = Math.cos(62 * Math.PI / 180);  // the camera's tilt, set per frame
const FINGER = [null, 'thumb', 'index-finger', 'middle-finger', 'ring-finger', 'pinky-finger'];
const SKIN = '#cc917f', NAIL = '#efcfc6';  // the back of the hand; the fingertips
// Distances in centimetres (the models are in metres); S below is page pixels per centimetre.
// A white key's width and length to these hands: smaller than a real key's (2.35 by 15), as in a
// piano video, whose camera is close above the hands so they look large on the keys.
const KEY_W = 2.0, KEY_LONG = 13;
const SIN_MIN = Math.sin(45 * Math.PI / 180);  // the camera's lowest tilt
// The fingers lie long and gently curved, as a pianist's do: the knuckles low over the keys and
// well behind the fingertips.
const KNUCKLES_UP = 3.3;    // the knuckles above the keys
const KNUCKLES_BACK = 6.3;  // and behind the fingertips
const PITCH = 0.1;          // the back of the hand rising from the wrist to the knuckles (radians)
const TIP = 0.35, LIFT = 1.0, REST = 1.9, DIP = 0.6;  // tip on a key; over its next key; resting; a key pressed down
const THUMB_AHEAD = 1.4;    // the thumb's tip on a white key, in front of the knuckles
// The thumb bends at its two joints about their own axes in the model (across the palm, toward
// the fingers, as a thumb's do): a little at rest, more to reach a key near its base or under the hand
const THUMB_BEND = [-0.1, 1.25], THUMB_MID = 0.6;  // radians at the last joint: from, to; the middle joint's share
const THUMB_TURN = 1.7;     // radians at most the thumb turns at its base from how the model holds it
const THUMB_REACH = 2.6;    // and on a black key at most this far in front of them
const THUMB_LOW = 0.8;      // cm lower than the fingers that a thumb at rest hangs
// the shorter fingers play a little nearer the front than the middle one, as a curved hand's tips lie
const DEPTH = [0, 0, 0.5, 0, 0.6, 2.6];
const REST_UP = 2.2, REST_BACK = 1.5, REST_LIFT = 1.6;  // a hand at rest: knuckles up, drawn back, fingertips up
// Hands that meet: the right rides over the left, its knuckles up and in toward the fallboard,
// the left's drawn toward the player; fully so once their fingertips are level
const OVER_UP = 1.6, OVER_IN = 2.6, UNDER_OUT = 1.4;
const ELBOW_OUT = 19, FOREARM = 30, ARM_DROP = 0.2;  // elbow beside the seat; forearm length; its slope
const ALONG_ARM = 0.6;      // how far the hand turns to lie along the forearm
// The hand as it moves: striking, its weight sinks into the key and the fingers not playing come
// up a little; travelling along the keys it lifts off them and its wrist leads the fingers.
const SINK = 0.35, COUNTER = 0.3;  // cm: the knuckles down on a pressed key; the other fingers up
// A finger isn't free of its neighbours: one at rest goes part of the way down with a neighbour
// that plays (the ring finger most, tied as it is to the middle and little fingers)
const FOLLOW = [0, 0, 0.12, 0.22, 0.4, 0.28];
// The hand rolls toward the side that's playing (the little finger's or the thumb's), as a
// forearm turns to put its weight behind a finger
const ROLL = 0.11;          // radians, with only the outermost finger down
// Fingers side by side: their tips this far apart at least (cm), so one at rest never lies on or
// crosses its neighbour; and a finger at rest stays this near (cm) to straight ahead of its knuckle
const TIP_GAP = 1.75, SPLAY = 1.3;
// A finger on its way to a key reaches no further to the side than this (cm) from straight
// ahead of its knuckle: the hand brings it the rest of the way, and only a finger playing is
// held to its key. The thumb, from the index's knuckle: out to the side, and in under the hand.
const STRETCH = 2.8, THUMB_OUT = 7.5, THUMB_UNDER = 4.5;
// How the hand's weight and place follow the fingers (ms): down into a key, back up; the roll;
// the shift toward a finger that can't reach
const SINK_MS = [45, 170], ROLL_MS = 130, SHIFT_MS = 90;
// Never quite still: the wrist floats a little (cm) and turns (radians), slowly, more at rest
const SWAY_UP = 0.07, SWAY_TURN = 0.008;
const TRAVEL_FAST = 70;     // cm a second along the keys: a leap's speed
const TRAVEL_UP = 1.3, TRAVEL_TIPS = 0.9, TRAVEL_TURN = 0.12;  // at that speed: knuckles up, resting tips up (cm); the turn (radians)
// A glissando (an organ's palm roll-up): the wrist rides up and the hand tips forward, so the
// fingers lie flat and their tips skim the keys as the palm slides along them
const GLIDE_UP = 1.4, GLIDE_PITCH = 0.2, GLIDE_TIPS = 1.7;  // cm the knuckles rise; radians the hand tips; cm the resting tips drop
const PIP_TO_DIP = 0.7;     // a finger's last joint bends this much of its middle one
// The forearm meets the hand at a shallow angle with the cut-off end of the model's wrist inside
// it. Rings at these distances (cm) from its start, with half-widths across and up (cm):
const ARM = [[0, 2.45, 1.7], [0.9, 2.62, 1.86], [1.7, 2.74, 1.97], [3, 2.8, 2.02], [6, 2.9, 2.12],
             [10, 3.05, 2.3], [16, 3.25, 2.5], [23, 3.4, 2.7], [31, 3.5, 2.85]];
const ARM_SIDES = 28, ARM_FROM = 0.05, WRIST_CUT = 0.067;  // model y (m): the tube's start; the cut

const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const _v = new THREE.Vector3(), _h = new THREE.Vector3(), _d = new THREE.Vector3(), _k = new THREE.Vector3();
const _p = new THREE.Vector3(), _e = new THREE.Vector3(), _c = new THREE.Vector3();
const _q = new THREE.Quaternion(), _qa = new THREE.Quaternion(), _qy = new THREE.Quaternion(), _qi = new THREE.Quaternion();
const _q1 = new THREE.Quaternion(), _q2 = new THREE.Quaternion();
const _m = new THREE.Matrix4();
// For checking: how far each fingertip ended up from its target in the last frame (cm)
// and where each hand and its joints were (cm): for hands_render.py's frames.json
export const debug = {misses: [], pose: []};

export async function create() {
  const canvas = document.createElement('canvas');
  const renderer = new THREE.WebGLRenderer({canvas, alpha: true, antialias: true});
  renderer.setClearColor(0x000000, 0);
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.VSMShadowMap;

  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera(0, 1, 1, 0, 1, 10000);
  camera.up.set(0, 0, 1);
  camera.position.set(0, -4000 * COS, 4000 * SIN);
  camera.lookAt(0, 0, 0);

  renderer.toneMapping = THREE.NeutralToneMapping;
  const sky = new THREE.HemisphereLight(0xfff3ec, 0x241f2a, 0.7);
  sky.position.set(0, 0, 1);
  scene.add(sky);
  const rim = new THREE.DirectionalLight(0xe6f4ff, 1.3);  // the lit keys, catching the fingers' far edges
  rim.position.set(0.2, 1, 0.35);
  scene.add(rim);
  const sun = new THREE.DirectionalLight(0xfffaf4, 2.6);  // from the upper left, a little behind the player
  sun.castShadow = true;
  sun.shadow.mapSize.set(1024, 1024);
  sun.shadow.radius = 9;
  sun.shadow.blurSamples = 16;
  scene.add(sun, sun.target);
  const fill = new THREE.DirectionalLight(0xcfe6ff, 0.45);  // the keys' cool light from the front
  fill.position.set(0.5, 1, 0.5);
  scene.add(fill);
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.ShadowMaterial({opacity: 0.4}));
  ground.receiveShadow = true;
  scene.add(ground);

  const loader = new GLTFLoader();
  const models = await Promise.all(['left', 'right'].map(s => loader.loadAsync(new URL(`./hands/${s}.glb`, import.meta.url).href)));
  const hands = {left: rig(models[0], -1), right: rig(models[1], 1)};
  for (const hand of Object.values(hands)) scene.add(hand.root, hand.arm, ...hand.glow);

  function rig(gltf, side) {
    const material = new THREE.MeshPhysicalMaterial({color: 0xffffff, vertexColors: true, roughness: 0.55,
      metalness: 0, sheen: 0.3, sheenColor: new THREE.Color('#ffc4ad'), sheenRoughness: 0.5});
    const root = new THREE.Group();
    root.matrixAutoUpdate = false;
    root.add(gltf.scene);
    const bones = {};
    let mesh = null;
    gltf.scene.traverse(o => { if (o.isBone) bones[o.name] = o; if (o.isSkinnedMesh) mesh = o; });
    if (!mesh || !bones.wrist) throw new Error('hand model without its skeleton');
    paint(mesh);
    mesh.material = material;
    mesh.castShadow = true;
    mesh.frustumCulled = false;
    const N = new THREE.Vector3(side, 0, 0);  // out of the back of the hand, in the model
    const fingers = [null];
    for (let f = 1; f <= 5; f++) {
      const names = (f === 1 ? ['metacarpal', 'phalanx-proximal', 'phalanx-distal', 'tip']
        : ['phalanx-proximal', 'phalanx-intermediate', 'phalanx-distal', 'tip']).map(j => `${FINGER[f]}-${j}`);
      const rest = names.map(n => ({p: bones[n].position.clone(), q: bones[n].quaternion.clone()}));
      const len = [], dir = [];
      for (let i = 0; i < 3; i++) {
        const d = rest[i + 1].p.clone().sub(rest[i].p);
        len.push(d.length());
        dir.push(d.normalize());
      }
      // straight ahead for this finger, along the back of the hand
      const ahead = rest[3].p.clone().sub(rest[0].p);
      ahead.addScaledVector(N, -ahead.dot(N)).normalize();
      // the axes the thumb's two joints bend about (the model's own: a joint's x), turned so
      // that a positive angle bends it toward the palm, away from the nail's side (its y)
      const axes = [1, 2].map(i => {
        const x = new THREE.Vector3(1, 0, 0).applyQuaternion(rest[i].q);
        const nail = new THREE.Vector3(0, 1, 0).applyQuaternion(rest[i].q);
        return x.multiplyScalar(_v.crossVectors(x, dir[i]).dot(nail) > 0 ? -1 : 1);
      });
      fingers.push({bones: names.map(n => bones[n]), rest, len, dir, ahead, axes});
    }
    const knuckles = new THREE.Vector3();
    for (let f = 2; f <= 5; f++) knuckles.add(fingers[f].rest[0].p);
    knuckles.multiplyScalar(0.25);
    // model → hand: the back of the hand up, the fingers forward, index to little finger outward
    const base = new THREE.Matrix4().set(0, 0, side, 0, 0, -1, 0, 0, side, 0, 0, 0, 0, 0, 0, 1);
    const glow = [];
    for (let f = 1; f <= 5; f++) glow.push(new THREE.PointLight(0xffffff, 0, 1, 0));
    const armSkin = material.clone();
    armSkin.vertexColors = false;
    armSkin.color.set(SKIN);
    // what the hand carries from frame to frame: its weight in the keys, its roll, its shift
    const state = {sink: 0, roll: 0, shift: new THREE.Vector3(), seen: false, clock: 0};
    return {side, root, mesh, glow, N, fingers, knuckles, base, state, H: new THREE.Matrix4(), Hinv: new THREE.Matrix4(),
            wrist: bones.wrist.position.clone(), ...forearm(mesh, armSkin)};
  }

  // The forearm: an oval tube that starts inside the wrist a little narrower than it and
  // leaves it a little wider, where the model's rounded wrist end is cut away (ARM, WRIST_CUT).
  function forearm(mesh, skin) {
    const g = mesh.geometry, pos = g.attributes.position;
    const keep = [];
    for (let t = 0; t < g.index.count; t += 3) {
      const tri = [g.index.getX(t), g.index.getX(t + 1), g.index.getX(t + 2)];
      if (!tri.every(i => pos.getY(i) > WRIST_CUT)) keep.push(...tri);
    }
    g.setIndex(keep);
    const tris = [];
    for (let j = 0; j < ARM.length - 1; j++) {
      for (let i = 0; i < ARM_SIDES; i++) {
        const a = j * ARM_SIDES + i, b = j * ARM_SIDES + (i + 1) % ARM_SIDES;
        tris.push(a, b, b + ARM_SIDES, a, b + ARM_SIDES, a + ARM_SIDES);  // facing out (rings go round as below)
      }
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(ARM.length * ARM_SIDES * 3), 3));
    geo.setIndex(tris);
    const arm = new THREE.Mesh(geo, skin);
    arm.castShadow = true;
    arm.frustumCulled = false;
    return {arm};
  }

  // Skin colour per vertex: paler toward the fingertips (by how much the last bone of a finger
  // moves the vertex), as nails and pads catch the light in a piano video.
  function paint(mesh) {
    const g = mesh.geometry, joints = g.attributes.skinIndex, weights = g.attributes.skinWeight;
    const names = mesh.skeleton.bones.map(b => b.name);
    const skin = new THREE.Color(SKIN), nail = new THREE.Color(NAIL), c = new THREE.Color();
    const colors = new Float32Array(g.attributes.position.count * 3);
    for (let i = 0; i < g.attributes.position.count; i++) {
      let tip = 0;
      for (let j = 0; j < 4; j++) {
        const name = names[joints.getComponent(i, j)] || '';
        if (/-(phalanx-distal|tip)$/.test(name)) tip += weights.getComponent(i, j);
      }
      c.copy(skin).lerp(nail, 0.75 * Math.min(1, tip));
      colors.set([c.r, c.g, c.b], i * 3);
    }
    g.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  }

  // The hand placed and its fingers bent so each tip reaches its target.
  function pose(hand, item, view, S) {
    const k = S * 100;  // page pixels per model metre
    const rest = item.rest || 0;
    // What the hand carries over from the last frame eases toward where it's going (times
    // stretched in slow motion, as roll.js's are); a hand first seen is put straight there.
    const st = hand.state;
    const dt = st.seen ? clamp(view.dt || 16, 0, 100) : 1e6;
    const ease = ms => 1 - Math.exp(-dt / (ms * (item.slow || 1)));
    st.clock = st.seen ? st.clock + dt / (item.slow || 1) : 0;
    st.seen = true;
    const front = -view.keyH / SIN;  // the keys' near edge
    // Where each finger plays its key: across where roll.js put it, down the key as far as a
    // finger of its length lies, and as far down as the key is pressed.
    const keyAt = [null], black = [0];
    for (let f = 1; f <= 5; f++) {
      const t = item.tips[f];
      const b = clamp((view.whiteY - t.y) / (view.whiteY - view.blackY), 0, 1);
      let y = -(t.y - view.floor) / SIN;
      if (f > 1) y -= DEPTH[f] * S * (1 - 0.5 * b);
      keyAt.push(new THREE.Vector3(t.x, y, (TIP + LIFT * (1 - t.press) - DIP * t.press) * S));
      black.push(b);
    }
    // the knuckles over the fingers' keys, a little behind them (higher and further back at
    // rest); the hand turned a little along the forearm, which comes from an elbow beside the seat
    let cx = 0, cy = 0;
    for (let f = 2; f <= 5; f++) { cx += keyAt[f].x / 4; cy += keyAt[f].y / 4; }
    const elbowX = view.seatX + hand.side * ELBOW_OUT * S;
    const speed = (item.speed || 0) / S;  // cm a second, to the right
    // accent: in slow motion (roll.js) a leap's lift and turn are made a little bigger, to be seen
    const travel = clamp(Math.abs(speed) / TRAVEL_FAST, 0, 1) ** 1.5 * (item.accent || 1);
    const sway = 1 + rest;  // the wrist's slow float, each hand in its own time
    const yaw = ALONG_ARM * Math.atan2(cx - elbowX, FOREARM * S) - TRAVEL_TURN * travel * Math.sign(speed)
      + SWAY_TURN * sway * Math.sin(st.clock / 950 + 2 * hand.side);
    const kn = hand.knuckles;
    const over = item.over || 0, under = item.under || 0;
    // How hard the hand is pressing (its most pressed finger) and on which side: its weight
    // goes into the key and comes back out more slowly than a finger does, and the hand rolls
    // toward the fingers that are down.
    let down = 0, lean = 0, total = 0;
    const pressed = [0, 0, 0, 0, 0, 0, 0];
    for (let f = 1; f <= 5; f++) {
      const w = pressed[f] = item.tips[f].press * item.tips[f].on;
      down = Math.max(down, w);
      lean += w * (f - 3) / 2;
      total += w;
    }
    st.sink += (down - st.sink) * ease(SINK_MS[down > st.sink ? 0 : 1]);
    st.roll += (ROLL * lean / Math.max(1, total) - st.roll) * ease(ROLL_MS);
    const sink = st.sink;
    const glide = item.glide || 0;
    const rise = KNUCKLES_UP + REST_UP * rest + OVER_UP * over + TRAVEL_UP * travel * (1 - glide) + GLIDE_UP * glide - SINK * sink
      + SWAY_UP * sway * Math.sin(st.clock / 640 + hand.side);
    const at = new THREE.Vector3(cx, cy - (KNUCKLES_BACK + REST_BACK * rest - OVER_IN * over + UNDER_OUT * under) * S, rise * S);
    // the hand is never so far back that its thumb would hang off the front of the keys (on
    // short keys it would otherwise come in for every thumb note and go back out after)
    at.y = Math.max(at.y, front + (0.8 - THUMB_AHEAD) * S);
    // a thumb going to a black key brings the hand in toward the fallboard after it
    const thumbIn = keyAt[1].y - THUMB_REACH * S;
    if (thumbIn > at.y) at.y += (thumbIn - at.y) * item.tips[1].on * black[1];
    const home = at.clone();
    // Each finger's target with the knuckles at `at`: its key, as far as it has gone to it (on),
    // from where it rests, which moves with the hand: hanging relaxed in front of its knuckle,
    // lifted off the keys. A white key is played where the finger reaches in front of the
    // knuckles, so a hand moved in (for a black key) plays its white keys further in too; the
    // thumb plays one in front of the knuckles, no further in than the fingers. A black key is
    // played on the key.
    const restZ = (TIP + REST + REST_LIFT * rest + TRAVEL_TIPS * travel * (1 - glide) - GLIDE_TIPS * glide) * S;
    const targets = [null, 1, 2, 3, 4, 5].map(f => f && new THREE.Vector3()), key = new THREE.Vector3();
    // "in front of the knuckles" is along the hand, which is turned (yaw): how far down the
    // keys finger f reaches at x, so a turned hand's fingertips lie on a slant, as its knuckles do
    const sinY = Math.sin(yaw), cosY = Math.cos(yaw);
    const ahead = (f, x) => at.y + ((f === 1 ? THUMB_AHEAD : KNUCKLES_BACK - DEPTH[f]) * S - (x - at.x) * sinY) / cosY;
    const aim = () => {
      for (let f = 1; f <= 5; f++) {
        const t = item.tips[f];
        key.copy(keyAt[f]);
        const reach = clamp(ahead(f, key.x), front + 0.8 * S, f === 1 ? key.y : -0.8 * S);
        key.y += (reach - key.y) * (1 - black[f]);
        // at rest: up off the keys (the thumb less, hanging beside the hand), a little higher
        // while the hand's weight is in another finger, but part of the way down with a
        // neighbour that's playing
        const beside = Math.max(pressed[f - 1], pressed[f + 1]) * (1 - t.press);
        const up = restZ + S * (COUNTER * Math.max(0, sink - t.press) - REST * FOLLOW[f] * beside - (f === 1 ? THUMB_LOW : 0));
        let x = t.x + at.x - home.x;
        // straight ahead of its knuckle (the thumb: of the index's), as the hand lies now
        const F = hand.fingers[Math.max(2, f)];
        _h.copy(F.rest[0].p).applyMatrix4(hand.H);
        _d.copy(F.ahead).transformDirection(hand.H);
        const line = _h.x + (ahead(f, x) - _h.y) * _d.x / Math.max(0.3, _d.y);
        if (f > 1) x = clamp(x, line - SPLAY * S, line + SPLAY * S);
        const to = targets[f].set(x, ahead(f, x), up).lerp(key, t.on);
        const out = f > 1 ? [STRETCH, STRETCH] : hand.side > 0 ? [THUMB_OUT, THUMB_UNDER] : [THUMB_UNDER, THUMB_OUT];
        to.x += (clamp(to.x, line - out[0] * S, line + out[1] * S) - to.x) * (1 - t.press * t.press);
      }
      // Fingers 2 to 5 side by side, in their order: the one less on a key gives way (a hand
      // shifted toward a far key brings its resting fingers along, up against the ones playing)
      for (let pass = 0; pass < 4; pass++) {
        for (let f = 2; f <= 4; f++) {
          const short = TIP_GAP * S - hand.side * (targets[f + 1].x - targets[f].x);
          const a = 1 - item.tips[f].on, b = 1 - item.tips[f + 1].on;
          if (short <= 0 || a + b < 1e-3) continue;
          targets[f].x -= hand.side * short * a / (a + b);
          targets[f + 1].x += hand.side * short * b / (a + b);
        }
      }
    };
    const tipAt = f => hand.fingers[f].bones[3].position.clone().applyMatrix4(hand.H);
    const place = () => {
      hand.H.makeTranslation(at.x, at.y, at.z)
        .multiply(_m.makeRotationZ(-yaw))
        .multiply(_m.makeRotationX(PITCH + GLIDE_PITCH * glide))
        .multiply(_m.makeRotationY(hand.side * st.roll))
        .multiply(_m.makeScale(k, k, k))
        .multiply(hand.base)
        .multiply(_m.makeTranslation(-kn.x, -kn.y, -kn.z));
      hand.Hinv.copy(hand.H).invert();
      aim();
      for (let f = 1; f <= 5; f++) {
        const local = targets[f].clone().applyMatrix4(hand.Hinv);
        if (f === 1) poseThumb(hand, local); else poseFinger(hand, f, local);
      }
    };
    for (let round = 0; round < 3; round++) {
      place();
      // A finger that can't reach its key moves the whole hand toward it, as a player's
      // hand shifts for a thumb or a stretch; fingers short of keys on both sides cancel out.
      // The more a finger is on its key and the further it's short, the more it counts, with
      // no sudden start, so the hand never jumps as a finger comes to a key.
      const shift = new THREE.Vector3();
      let weight = 0;
      for (let f = 1; f <= 5; f++) {
        const t = item.tips[f];
        const tip = tipAt(f), miss = targets[f].clone().sub(tip);
        // a thumb short of its place on a white key is still on the key: the hand stays back
        if (f === 1 && miss.y > 0 && tip.y > front + 0.3 * S) miss.y *= black[1];
        const far = miss.length(), u = clamp((t.on - 0.1) / 0.5, 0, 1);
        const w = u * u * (3 - 2 * u) * (0.4 + t.press);
        if (far < 1e-6 || !w) continue;
        shift.addScaledVector(miss, w * Math.max(0, far - 0.15 * S) / far);
        weight += w;
      }
      if (!weight) break;
      shift.multiplyScalar(1 / Math.max(0.4, weight));
      shift.z *= 0.5;
      at.add(shift);
      at.sub(home).clampLength(0, 3 * S).add(home);
      at.z = clamp(at.z, (rise - 1.2) * S, (rise + 0.6) * S);
    }
    st.shift.lerp(_v.copy(at).sub(home), ease(SHIFT_MS));
    at.copy(home).add(st.shift);
    place();
    hand.root.matrix.copy(hand.H);
    hand.root.matrixWorldNeedsUpdate = true;

    // the forearm, from inside the wrist to the elbow below the page: it leaves the wrist along
    // the hand and curves toward the elbow
    const start = new THREE.Vector3(hand.wrist.x, ARM_FROM, hand.wrist.z).applyMatrix4(hand.H);
    const elbow = new THREE.Vector3(elbowX, start.y - FOREARM * S * Math.cos(ARM_DROP), start.z - FOREARM * S * Math.sin(ARM_DROP));
    const out = new THREE.Vector3(0, 1, 0).transformDirection(hand.H);  // from the hand toward the arm
    const across = new THREE.Vector3(0, 0, 1).transformDirection(hand.H);
    // round from across to the back of the hand on the right, the other way on the left (mirrored)
    const up = new THREE.Vector3(1, 0, 0).transformDirection(hand.H);
    const reach = start.distanceTo(elbow), bend = start.clone().addScaledVector(out, 0.35 * reach);
    const pos = hand.arm.geometry.attributes.position, mid = new THREE.Vector3();
    ARM.forEach(([u, wide, high], j) => {
      const t = Math.min(1, u * S / reach);
      mid.set(0, 0, 0).addScaledVector(start, (1 - t) * (1 - t)).addScaledVector(bend, 2 * (1 - t) * t).addScaledVector(elbow, t * t);
      for (let i = 0; i < ARM_SIDES; i++) {
        const a = 2 * Math.PI * i / ARM_SIDES;
        _e.copy(mid).addScaledVector(across, Math.cos(a) * wide * S).addScaledVector(up, Math.sin(a) * high * S);
        pos.setXYZ(j * ARM_SIDES + i, _e.x, _e.y, _e.z);
      }
    });
    pos.needsUpdate = true;
    hand.arm.geometry.computeVertexNormals();

    // a pressing fingertip lit by its key, and where to print each finger's number
    const color = new THREE.Color().setRGB(item.tint[0] / 255, item.tint[1] / 255, item.tint[2] / 255, THREE.SRGBColorSpace);
    const labels = [];
    for (let f = 1; f <= 5; f++) {
      const F = hand.fingers[f], t = item.tips[f];
      const tip = tipAt(f);
      const local = targets[f].clone().applyMatrix4(hand.Hinv), from = F.rest[0].p;
      const missed = tip.clone().sub(targets[f]).divideScalar(S);
      debug.misses.push({hand: item.hand, f, cm: +(tip.distanceTo(targets[f]) / S).toFixed(2),
                         // how far the target is from the finger's first joint, and the finger's length (cm)
                         far: +(local.distanceTo(from) * 100).toFixed(2), len: +(F.len.reduce((a, b) => a + b, 0) * 100).toFixed(2),
                         off: [+missed.x.toFixed(1), +missed.y.toFixed(1), +missed.z.toFixed(1)]});
      const light = hand.glow[f - 1];
      light.color.copy(color);
      light.intensity = 6 * t.press * t.on;
      light.distance = 3.5 * S;
      light.position.set(tip.x, tip.y + 0.9 * S, tip.z + 1.0 * S);
      const mid = F.bones[1].position.clone().lerp(F.bones[2].position, f === 1 ? 0.5 : 0.35).applyMatrix4(hand.H);
      labels.push({f, x: mid.x, y: view.floor - (mid.y * SIN + mid.z * COS), alpha: item.alpha});
    }
    const cm = v => [+(v.x / S).toFixed(2), +(v.y / S).toFixed(2), +(v.z / S).toFixed(2)];
    debug.pose.push({hand: item.hand, at: cm(at), yaw: +yaw.toFixed(3),
                     joints: [1, 2, 3, 4, 5].map(f => hand.fingers[f].bones.map(b => cm(b.position.clone().applyMatrix4(hand.H))))});
    return {labels, center: new THREE.Vector3(cx, cy, 0)};
  }

  // Fingers 2 to 5: turned toward the target at the knuckle, then bent at the knuckle and
  // the two joints after it (the last following the middle one) until the tip reaches it.
  function poseFinger(hand, f, target) {
    const F = hand.fingers[f], N = hand.N, L = F.len;
    const base = F.rest[0].p;
    _v.copy(target).sub(base);
    _h.copy(_v).addScaledVector(N, -_v.dot(N));
    const yaw = clamp(Math.atan2(_p.crossVectors(F.ahead, _h).dot(N), F.ahead.dot(_h)), -0.5, 0.5);
    _d.copy(F.ahead).applyAxisAngle(N, yaw);
    const u = _v.dot(_d), w = _v.dot(N);
    const chain = b => {
      const b2 = b * (1 + PIP_TO_DIP);
      return [L[0] + L[1] * Math.cos(b) + L[2] * Math.cos(b2), L[1] * Math.sin(b) + L[2] * Math.sin(b2)];
    };
    const b = reachBend(Math.hypot(u, w), 0, 1.6, x => Math.hypot(...chain(x)));
    const [cx, cy] = chain(b);
    const a = clamp(Math.atan2(-w, u) - Math.atan2(cy, cx), -0.35, 1.6);
    _k.crossVectors(N, _d).normalize();  // turning about this bends the finger toward the palm
    _qy.setFromAxisAngle(N, yaw);
    const angles = [a, a + b, a + b * (1 + PIP_TO_DIP)];
    _p.copy(base);
    for (let i = 0; i < 4; i++) {
      const j = Math.min(i, 2);
      _qa.setFromAxisAngle(_k, angles[j]);
      _q.setFromUnitVectors(F.dir[j], F.ahead);
      F.bones[i].quaternion.copy(_qa).multiply(_qy).multiply(_q).multiply(F.rest[i].q);
      F.bones[i].position.copy(_p);
      if (i < 3) _p.addScaledVector(_e.copy(_d).applyAxisAngle(_k, angles[i]), L[i]);
    }
  }

  // The thumb: bent at its two joints (about their own axes, so it folds across the palm) until
  // it's as long as the way to its target, then turned at its base to point there.
  function poseThumb(hand, target) {
    const F = hand.fingers[1], L = F.len, e = F.dir, base = F.rest[0].p;
    const chain = b => {
      _q1.setFromAxisAngle(F.axes[0], THUMB_MID * b);
      _q2.setFromAxisAngle(F.axes[1], b).premultiply(_q1);
      return _c.set(0, 0, 0).addScaledVector(e[0], L[0])
        .addScaledVector(_e.copy(e[1]).applyQuaternion(_q1), L[1])
        .addScaledVector(_e.copy(e[2]).applyQuaternion(_q2), L[2]);
    };
    _v.copy(target).sub(base);
    const b = reachBend(_v.length(), THUMB_BEND[0], THUMB_BEND[1], x => chain(x).length());
    chain(b);
    _q.setFromUnitVectors(_c.normalize(), _v.normalize());
    const turn = 2 * Math.acos(clamp(Math.abs(_q.w), 0, 1));
    if (turn > THUMB_TURN) _q.copy(_qi.identity().slerp(_q, THUMB_TURN / turn));
    _q1.premultiply(_q);
    _q2.premultiply(_q);
    const turns = [_q, _q1, _q2, _q2];
    _p.copy(base);
    for (let i = 0; i < 4; i++) {
      F.bones[i].quaternion.copy(turns[i]).multiply(F.rest[i].q);
      F.bones[i].position.copy(_p);
      if (i < 3) _p.addScaledVector(_e.copy(e[i]).applyQuaternion(turns[i]), L[i]);
    }
  }

  // The bend in [lo, hi] at which a chain reaches dist (it reaches less the more it bends).
  function reachBend(dist, lo, hi, reachOf) {
    if (reachOf(lo) <= dist) return lo;
    if (reachOf(hi) >= dist) return hi;
    for (let i = 0; i < 20; i++) {
      const m = (lo + hi) / 2;
      if (reachOf(m) > dist) lo = m; else hi = m;
    }
    return (lo + hi) / 2;
  }

  // Draw the hands in list ({hand, alpha, tint, tips[1..5]: {x, y, press, on}}) onto ctx, in
  // page pixels (speed: how fast the hand is moving along the keys, pixels a second; slow: how
  // many times slower than at tempo it's moving; view.dt: ms since the last frame); returns
  // where to print each finger's number.
  function draw(ctx, view, list) {
    const {w, h, dpr} = view;
    if (!list.length) return [];
    const pw = Math.round(w * dpr), ph = Math.round(h * dpr);
    if (canvas.width !== pw || canvas.height !== ph) { renderer.setPixelRatio(dpr); renderer.setSize(w, h, false); }
    // a knuckle to a white key, as a hand's are on a real piano, and keys as long as a real
    // piano's: the camera tilts to draw them as long as roll.js did, but no lower than SIN_MIN
    // (from further behind, the forearms hide the hands), so keys drawn shorter than that are
    // shorter than a piano's and the hands reach a little past their near end
    const S = view.ww / KEY_W;
    SIN = clamp(view.keyH / (KEY_LONG * S), SIN_MIN, 0.97);
    COS = Math.sqrt(1 - SIN * SIN);
    camera.position.set(0, -4000 * COS, 4000 * SIN);
    camera.lookAt(0, 0, 0);
    camera.left = 0; camera.right = w; camera.top = view.floor; camera.bottom = view.floor - h;
    camera.updateProjectionMatrix();
    const keysLong = view.keyH / SIN;
    ground.position.set(w / 2, -keysLong, -0.9 * S);
    ground.scale.set(w * 3, h * 6, 1);

    for (const [name, hand] of Object.entries(hands)) {
      hand.root.visible = hand.arm.visible = false;
      for (const l of hand.glow) l.intensity = 0;
      if (!list.some(i => i.hand === name)) hand.state.seen = false;
    }
    const labels = [];
    debug.misses = [];
    debug.pose = [];
    // hands that meet ride one over the other (OVER_UP ...): from when their nearest fingertips
    // are a key and a half apart, fully once they're level
    const left = list.find(i => i.hand === 'left'), right = list.find(i => i.hand === 'right');
    if (left && right) {
      const tips = i => i.tips.slice(1).map(t => t.x);
      const u = clamp((Math.max(...tips(left)) - Math.min(...tips(right)) + 1.5 * view.ww) / (1.5 * view.ww), 0, 1);
      right.over = left.under = u * u * (3 - 2 * u);
    }
    const center = new THREE.Vector3();
    let spanX = 0;
    const posed = list.map(item => {
      const hand = hands[item.hand];
      const out = pose(hand, item, view, S);
      labels.push(...out.labels);
      center.add(out.center);
      return {hand, alpha: item.alpha, center: out.center};
    });
    center.multiplyScalar(1 / posed.length);
    for (const p of posed) spanX = Math.max(spanX, Math.abs(p.center.x - center.x));
    // the sun's shadow camera around the hands
    const r = spanX + 30 * S;
    sun.target.position.copy(center);
    sun.position.copy(center).add(new THREE.Vector3(-0.75, -0.35, 0.8).normalize().multiplyScalar(3000));
    Object.assign(sun.shadow.camera, {left: -r, right: r, top: r, bottom: -r, near: 1, far: 6000});
    sun.shadow.camera.updateProjectionMatrix();

    // one pass when the hands are equally faint, else one per hand
    const together = posed.every(p => p.alpha === posed[0].alpha);
    const passes = together ? [posed] : posed.map(p => [p]);
    for (const pass of passes) {
      for (const p of posed) p.hand.root.visible = p.hand.arm.visible = pass.includes(p);
      renderer.render(scene, camera);
      ctx.save();
      ctx.globalAlpha = pass[0].alpha;
      ctx.drawImage(canvas, 0, 0, w, h);
      ctx.restore();
    }
    return labels;
  }

  return {draw, debug};
}
