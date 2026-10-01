import { describe, expect, it } from "vitest";
import { connection, endpoint } from "./connection";

describe("connection", () => {
  it("lee la inyección de Tauri", () => {
    expect(connection({ __JARVIS__: { port: 8765, token: "abc" } }, "")).toEqual({ port: 8765, token: "abc" });
  });
  it("la inyección tiene prioridad sobre la URL", () => {
    expect(connection({ __JARVIS__: { port: 1, token: "a" } }, "?port=2&token=b")).toEqual({ port: 1, token: "a" });
  });
  it("cae a la URL si no hay inyección o es inválida", () => {
    expect(connection({}, "?port=8765&token=xyz")).toEqual({ port: 8765, token: "xyz" });
    expect(connection({ __JARVIS__: { port: 0, token: "a" } }, "?port=9&token=t")).toEqual({ port: 9, token: "t" });
    expect(connection({ __JARVIS__: "x" }, "?port=9&token=t")).toEqual({ port: 9, token: "t" });
  });
  it("rechaza puertos y tokens inválidos", () => {
    for (const s of ["?port=0&token=a", "?port=70000&token=a", "?port=80.5&token=a", "?port=abc&token=a", "?port=80&token=", "?port=80", "?token=a"])
      expect(connection({}, s)).toBeNull();
    expect(connection({ __JARVIS__: { port: "8765", token: "a" } }, "")).toEqual({ port: 8765, token: "a" });
    expect(connection({ __JARVIS__: { port: true, token: "a" } }, "")).toBeNull();
  });
  it("construye la URL con el token escapado", () => {
    expect(endpoint({ port: 8765, token: "a b&c" })).toBe("ws://127.0.0.1:8765/?token=a%20b%26c");
    expect(endpoint(null)).toBeNull();
  });
});
