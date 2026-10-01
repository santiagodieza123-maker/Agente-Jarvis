import { Canvas, useFrame } from "@react-three/fiber";
import { useRef } from "react";
import * as THREE from "three";
import type { AgentState } from "../store";

const COLORS: Record<AgentState, string> = {
  idle: "#2fb8ff", thinking: "#7de7ff", acting: "#00ffd0", awaiting: "#ffb020", error: "#ff3b3b", killed: "#552222",
};
const SPEED: Record<AgentState, number> = { idle: 0.2, thinking: 1.2, acting: 2.2, awaiting: 0.4, error: 0.1, killed: 0 };

function Reactor({ state }: { state: AgentState }) {
  const core = useRef<THREE.Mesh>(null);
  const rings = useRef<(THREE.Mesh | null)[]>([]);
  const color = COLORS[state];
  useFrame(({ clock }, dt) => {
    const t = clock.elapsedTime, k = SPEED[state];
    if (core.current) {
      const pulse = state === "killed" ? 0.3 : 1 + Math.sin(t * (1 + k * 2)) * 0.06;
      core.current.scale.setScalar(pulse);
      core.current.rotation.y += dt * k * 0.5;
    }
    rings.current.forEach((r, i) => {
      if (!r) return;
      r.rotation.x += dt * k * (0.4 + i * 0.25) * (i % 2 ? -1 : 1);
      r.rotation.y += dt * k * (0.3 + i * 0.2);
    });
  });
  return (
    <group>
      <mesh ref={core}>
        <icosahedronGeometry args={[0.7, 2]} />
        <meshBasicMaterial color={color} wireframe transparent opacity={0.9} />
      </mesh>
      <mesh scale={0.45}>
        <sphereGeometry args={[1, 24, 24]} />
        <meshBasicMaterial color={color} transparent opacity={0.35} blending={THREE.AdditiveBlending} depthWrite={false} />
      </mesh>
      {[1.1, 1.4, 1.75].map((r, i) => (
        <mesh key={r} ref={(m) => { rings.current[i] = m; }}>
          <torusGeometry args={[r, 0.012 + i * 0.004, 8, 128]} />
          <meshBasicMaterial color={color} transparent opacity={0.75 - i * 0.15} />
        </mesh>
      ))}
    </group>
  );
}

export function Orb({ state }: { state: AgentState }) {
  return (
    <Canvas camera={{ position: [0, 0, 5.2], fov: 45 }} gl={{ alpha: true }} style={{ background: "transparent" }}>
      <Reactor state={state} />
    </Canvas>
  );
}
