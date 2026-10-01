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
      const r = 1.25 + Math.random() * 1.35, th = Math.random() * Math.PI * 2, ph = Math.acos(2 * Math.random() - 1);
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
      <pointsMaterial ref={mat} color={color} size={0.035} sizeAttenuation transparent opacity={0.75} depthWrite={false} blending={THREE.AdditiveBlending} />
    </points>
  );
}

function Reactor({ state, theme, level, compact }: { state: AgentState; theme: Theme; level: number; compact: boolean }) {
  const core = useRef<THREE.Mesh>(null);
  const halo = useRef<THREE.Mesh>(null);
  const rings = useRef<(THREE.Mesh | null)[]>([]);
  const pulse = useRef(0);
  const color = stateColor(state, theme);
  const { camera, pointer } = useThree();
  useEffect(() => { pulse.current = 1; }, [state]);                    // destello al cambiar de estado
  useFrame(({ clock }, dt) => {
    const t = clock.elapsedTime, k = SPEED[state] * (reduced() ? 0.3 : 1);
    pulse.current *= 0.93;
    const burst = 1 + pulse.current * 0.18 + level * 0.25;
    if (core.current) {
      const base = state === "killed" ? 0.3 : 1 + Math.sin(t * (1 + k * 2)) * 0.06;
      core.current.scale.setScalar(base * burst);
      core.current.rotation.y += dt * k * 0.5;
    }
    if (halo.current) halo.current.scale.setScalar(0.45 * burst * (1 + pulse.current * 0.3));
    rings.current.forEach((r, i) => {
      if (!r) return;
      r.rotation.x += dt * (k + level * 2) * (0.4 + i * 0.25) * (i % 2 ? -1 : 1);
      r.rotation.y += dt * (k + level * 2) * (0.3 + i * 0.2);
    });
    // paralaje suave con el ratón: el reactor «sigue» al puntero
    camera.position.x += (pointer.x * 0.5 - camera.position.x) * Math.min(1, dt * 2);
    camera.position.y += (pointer.y * 0.35 - camera.position.y) * Math.min(1, dt * 2);
    camera.lookAt(0, 0, 0);
  });
  return (
    <group>
      <mesh ref={core}>
        <icosahedronGeometry args={[0.7, 2]} />
        <meshBasicMaterial color={color} wireframe transparent opacity={0.9} />
      </mesh>
      <mesh ref={halo} scale={0.45}>
        <sphereGeometry args={[1, 24, 24]} />
        <meshBasicMaterial color={color} transparent opacity={0.4} blending={THREE.AdditiveBlending} depthWrite={false} />
      </mesh>
      {[1.1, 1.4, 1.75].map((r, i) => (
        <mesh key={r} ref={(m) => { rings.current[i] = m; }}>
          <torusGeometry args={[r, 0.012 + i * 0.004, 8, 128]} />
          <meshBasicMaterial color={color} transparent opacity={0.75 - i * 0.15} />
        </mesh>
      ))}
      <Particles state={state} color={color} count={compact ? 160 : 520} level={level} />
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
