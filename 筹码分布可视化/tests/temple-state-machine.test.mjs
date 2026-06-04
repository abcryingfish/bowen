import test from "node:test";
import assert from "node:assert/strict";
import { createTempleStateMachine } from "../assets/js/void-temple/temple-state-machine.js";

test("temple reaches ascended after four node activations", () => {
  const temple = createTempleStateMachine();
  temple.activateNode("north");
  temple.activateNode("south");
  temple.activateNode("east");
  const result = temple.activateNode("west");
  assert.equal(result.phase.name, "Ascended");
  assert.equal(temple.state.activatedCount, 4);
});
