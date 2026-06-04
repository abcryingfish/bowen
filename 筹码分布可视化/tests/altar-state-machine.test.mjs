import test from "node:test";
import assert from "node:assert/strict";
import { createAltarStateMachine } from "../assets/js/signal-altar/altar-state-machine.js";

test("altar enters ascended after overload plus enough links", () => {
  const altar = createAltarStateMachine();
  altar.activateNode("a1");
  altar.activateNode("a2");
  altar.linkNodes("a1", "a2");
  altar.activateNode("a3");
  altar.linkNodes("a2", "a3");
  const result = altar.triggerOverload();
  assert.equal(result.phase.name, "Ascended");
});
