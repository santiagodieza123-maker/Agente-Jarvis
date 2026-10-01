import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { Bloom, EffectComposer } from "@react-three/postprocessing";
import { Component, useEffect, useMemo, useRef, type ReactNode } from "react";
import * as THREE from "three";
import { themeOf, type Theme } from "../themes";
import type { AgentState } from "../store";

const SPEED: Record<AgentState, number> = { idle: 0.2, thinking: 1.2, acting: 2.2, awaiting: 0.4, error: 0.1, killed: 0 };
const BLOOM: Record<AgentState, number> = { idle: 0.55, thinking: 0.9, acting: 1.3, awaiting: 1.0, error: 1.2, killed: 0.08 };

export function stateColor(state: AgentState, theme: Theme): string {
  switch (state) {
    case "idle": return theme.idle;
    case "thinking": return theme.thinking;
    case "acting": return "#00ffd0";
    case "awaiting": return "#ffb020";
    case "error": return "#ff3b3b";
    default: return "#552222";
  }
}

const reduced = () => typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** Nube de partículas en capas esféricas que orbita el reactor; se contrae al activarse el pánico. */
function Particles({ state, color, count, level }: { state: AgentState; color: string; count: number; level: number }) {
  const ref = useRef<THREE.Points>(null);
  const mat = useRef<THREE.PointsMaterial>(null);
  const positions = useMemo(() => {
    const a = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      const r = 0.6 + Math.random() * 1.9, th = Math.random() * Math.PI * 2, ph = Math.acos(2 * Math.random() - 1);
      a[i * 3] = r * Math.sin(ph) * Math.cos(th); a[i * 3 + 1] = r * Math.sin(ph) * Math.sin(th); a[i * 3 + 2] = r * Math.cos(ph);
    }
    return a;
  }, [count]);
  const k = useRef(1);
  useFrame((_, dt) => {
    const p = ref.current; if (!p) return;
    const speed = (SPEED[state] + level * 2) * (reduced() ? 0.3 : 1);
    p.rotation.y += dt * (0.05 + speed * 0.15);
    p.rotation.x += dt * speed * 0.04;
    const target = state === "killed" ? 0.12 : 1;
    k.current += (target - k.current) * Math.min(1, dt * 3);          // colapso suave
    p.scale.setScalar(k.current);
    if (mat.current) mat.current.opacity = state === "killed" ? 0.2 : 0.75;
  });
  return (
    <points ref={ref}>
      <bufferGeometry><bufferAttribute attach="attributes-position" args={[positions, 3]} /></bufferGeometry>
      <pointsMaterial ref={mat} color={color} size={0.03} sizeAttenuation transparent opacity={0.75} depthWrite={false} blending={THREE.AdditiveBlending} />
    </points>
  );
}

/** Esfera holográfica: miles de trazos tipo circuito sobre capas esféricas (en su mayoría alineados a paralelos/meridianos), con brillo irregular. */
function shellGeometry(radius: number, count: number): THREE.BufferGeometry {
  const pos = new Float32Array(count * 6), col = new Float32Array(count * 6);
  const p = new THREE.Vector3(), a = new THREE.Vector3(), b = new THREE.Vector3(), e = new THREE.Vector3(), n = new THREE.Vector3();
  for (let i = 0; i < count; i++) {
    const th = Math.random() * Math.PI * 2, ph = Math.acos(2 * Math.random() - 1);
    n.set(Math.sin(ph) * Math.cos(th), Math.cos(ph), Math.sin(ph) * Math.sin(th));
    const east = new THREE.Vector3(-Math.sin(th), 0, Math.cos(th)), north = new THREE.Vector3().crossVectors(east, n);
    const along = Math.random() < 0.5 ? east : north, tilt = Math.random() < 0.06 ? (Math.random() - 0.5) : 0;
    e.copy(along).addScaledVector(along === east ? north : east, tilt).normalize();
    const len = (0.02 + Math.pow(Math.random(), 3) * 0.2) / (0.6 + radius * 0.4);
    p.copy(n).multiplyScalar(radius * (1 + (Math.random() - 0.5) * 0.04));
    a.copy(p).addScaledVector(e, -len / 2).normalize().multiplyScalar(radius);
    b.copy(p).addScaledVector(e, len / 2).normalize().multiplyScalar(radius);
    pos.set([a.x, a.y, a.z, b.x, b.y, b.z], i * 6);
    const hot = Math.random() < 0.12 ? 1.4 : 0.3 + Math.random() * 0.6;            // algunos trazos casi blancos, la mayoría tenues
    col.set([hot, hot, hot, hot, hot, hot], i * 6);
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.BufferAttribute(pos, 3)); g.setAttribute("color", new THREE.BufferAttribute(col, 3));
  return g;
}

const SHELLS: { r: number; n: number; axis: [number, number, number]; w: number; o: number }[] = [
  { r: 0.62, n: 1000, axis: [0.3, 1, 0.1], w: 1.6, o: 0.95 }, { r: 0.92, n: 1800, axis: [1, 0.2, 0.4], w: -1.1, o: 0.9 },
  { r: 1.25, n: 2600, axis: [0.1, 1, 0.5], w: 0.8, o: 0.85 }, { r: 1.6, n: 3400, axis: [0.6, 0.3, 1], w: -0.55, o: 0.8 },
  { r: 1.95, n: 4200, axis: [0, 1, 0.2], w: 0.35, o: 0.75 }, { r: 2.2, n: 2600, axis: [0.4, 1, 0.8], w: -0.25, o: 0.55 },
];
const SWOOSH: { r: number; arc: number; tube: number; tilt: [number, number, number]; w: number }[] = [
  { r: 1.45, arc: 3.6, tube: 0.016, tilt: [1.2, 0.2, 0.4], w: 0.9 }, { r: 1.05, arc: 2.6, tube: 0.012, tilt: [0.3, 1.1, 0.2], w: -1.3 },
  { r: 1.8, arc: 2.2, tube: 0.01, tilt: [0.5, 0.2, 1.4], w: 0.6 }, { r: 0.7, arc: 4.4, tube: 0.012, tilt: [0.9, 0.9, 0], w: 1.8 },
  { r: 1.25, arc: 1.7, tube: 0.008, tilt: [0.1, 0.6, 1.0], w: -0.8 }, { r: 1.6, arc: 3.1, tube: 0.008, tilt: [1.4, 0.4, 0.9], w: 0.5 },
  { r: 0.9, arc: 2.0, tube: 0.01, tilt: [0.7, 1.4, 0.3], w: 1.1 }, { r: 2.0, arc: 1.4, tube: 0.012, tilt: [0.2, 0.3, 0.5], w: -0.4 },
];

function Reactor({ state, theme, level, compact }: { state: AgentState; theme: Theme; level: number; compact: boolean }) {
  const root = useRef<THREE.Group>(null);
  const shells = useRef<(THREE.LineSegments | null)[]>([]);
  const swooshes = useRef<(THREE.Mesh | null)[]>([]);
  const core = useRef<THREE.Mesh>(null);
  const halo = useRef<THREE.Mesh>(null);
  const pulse = useRef(0), k = useRef(1);
  const color = stateColor(state, theme);
  const { camera, pointer } = useThree();
  const geos = useMemo(() => SHELLS.map((s) => shellGeometry(s.r, Math.round(s.n * (compact ? 0.3 : 1)))), [compact]);
  useEffect(() => { pulse.current = 1; }, [state]);                    // destello al cambiar de estado
  useFrame(({ clock }, dt) => {
    const t = clock.elapsedTime, sp = SPEED[state] * (reduced() ? 0.3 : 1) + level * 1.5;
    pulse.current *= 0.93;
    const burst = 1 + pulse.current * 0.12 + level * 0.18;
    k.current += ((state === "killed" ? 0.1 : 1) - k.current) * Math.min(1, dt * 3);          // colapso suave
    root.current?.scale.setScalar(k.current * burst);
    shells.current.forEach((m, i) => {
      if (!m) return;
      const s = SHELLS[i], ax = s.axis;
      m.rotation.y += dt * s.w * (0.15 + sp * 0.35); m.rotation.x += dt * ax[0] * s.w * 0.06 * (1 + sp); m.rotation.z += dt * ax[2] * s.w * 0.04 * (1 + sp);
      (m.material as THREE.LineBasicMaterial).opacity = (state === "killed" ? 0.2 : s.o) * (0.88 + Math.sin(t * 1.3 + i) * 0.12);
    });
    swooshes.current.forEach((m, i) => {
      if (!m) return;
      const w = SWOOSH[i].w;
      m.rotation.z += dt * w * (0.25 + sp * 0.5); m.rotation.y += dt * w * 0.08 * (1 + sp);
    });
    if (core.current) { core.current.rotation.y += dt * (0.6 + sp); core.current.rotation.x += dt * 0.3; core.current.scale.setScalar(1 + Math.sin(t * (1 + sp)) * 0.06); }
    if (halo.current) halo.current.scale.setScalar(0.34 * (1 + Math.sin(t * 0.8) * 0.05 + pulse.current * 0.3));
    // paralaje suave con el ratón: la esfera «sigue» al puntero
    camera.position.x += (pointer.x * 0.5 - camera.position.x) * Math.min(1, dt * 2);
    camera.position.y += (pointer.y * 0.35 - camera.position.y) * Math.min(1, dt * 2);
    camera.lookAt(0, 0, 0);
  });
  return (
    <group ref={root}>
      {geos.map((g, i) => (
        <lineSegments key={i} ref={(m) => { shells.current[i] = m; }} geometry={g} rotation={[SHELLS[i].axis[0] * 3, i, SHELLS[i].axis[2] * 2]}>
          <lineBasicMaterial color={color} vertexColors transparent opacity={SHELLS[i].o} blending={THREE.AdditiveBlending} depthWrite={false} />
        </lineSegments>
      ))}
      {SWOOSH.map((s, i) => (
        <mesh key={i} ref={(m) => { swooshes.current[i] = m; }} rotation={s.tilt}>
          <torusGeometry args={[s.r, s.tube, 6, 180, s.arc]} />
          <meshBasicMaterial color={color} transparent opacity={0.9} blending={THREE.AdditiveBlending} depthWrite={false} />
        </mesh>
      ))}
      <mesh ref={core}>
        <icosahedronGeometry args={[0.3, 1]} />
        <meshBasicMaterial color={color} wireframe transparent opacity={0.9} blending={THREE.AdditiveBlending} />
      </mesh>
      <mesh ref={halo} scale={0.34}>
        <sphereGeometry args={[1, 24, 24]} />
        <meshBasicMaterial color={color} transparent opacity={0.28} blending={THREE.AdditiveBlending} depthWrite={false} />
      </mesh>
      <Particles state={state} color={color} count={compact ? 200 : 900} level={level} />
    </group>
  );
}

/** Si WebGL no está disponible, un reactor CSS en su lugar (el HUD no se queda sin orbe ni se rompe). */
class Fallback extends Component<{ state: AgentState; theme: Theme; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (!this.state.failed) return this.props.children;
    const c = stateColor(this.props.state, this.props.theme);
    return <div className="orb-css" data-testid="orb-fallback" style={{ ["--oc" as string]: c }} role="img" aria-label={`Estado: ${this.props.state}`} />;
  }
}

export function Orb({ state, theme, level = 0, compact = false }: { state: AgentState; theme?: string; level?: number; compact?: boolean }) {
  const th = themeOf(theme);
  return (
    <Fallback state={state} theme={th}>
      <Canvas camera={{ position: [0, 0, 5.2], fov: 45 }} dpr={[1, 1.5]} gl={{ alpha: true, antialias: false }} style={{ background: "transparent" }} data-testid="orb-canvas">
        <Reactor state={state} theme={th} level={level} compact={compact} />
        <EffectComposer multisampling={0}>
          <Bloom intensity={BLOOM[state] + level * 0.6} luminanceThreshold={0.12} luminanceSmoothing={0.85} mipmapBlur />
        </EffectComposer>
      </Canvas>
    </Fallback>
  );
}
