"use strict";

const assert = require("node:assert/strict");
const Module = require("node:module");
const path = require("node:path");

const originalLoad = Module._load;
class Plugin {}

Module._load = function(request, parent, isMain) {
  if (request === "@codemirror/view") {
    return { EditorView: { updateListener: { of: (listener) => listener } } };
  }
  if (request === "obsidian") {
    return {
      Notice: class Notice {},
      Plugin,
      addIcon: () => {},
      moment: () => ({
        format: (value) => value === "YYYY-MM-DD" ? "2026-09-01" : "2026-09-01",
      }),
      normalizePath: (value) => value.replaceAll("//", "/"),
    };
  }
  return originalLoad.call(this, request, parent, isMain);
};

const GoalWatchPlugin = require(path.resolve(__dirname, "../integrations/obsidian/goalwatch/main.js"));
Module._load = originalLoad;

function pluginWithApp() {
  const plugin = new GoalWatchPlugin();
  plugin.app = {
    internalPlugins: {
      getPluginById: () => ({
        enabled: true,
        instance: { options: { folder: "daily", format: "YYYY-MM-DD" } },
      }),
    },
  };
  return plugin;
}

function testDailyResolution() {
  const daily = pluginWithApp().dailyInfo();
  assert.deepEqual(daily, { dailyDate: "2026-09-01", file: "daily/2026-09-01.md" });
}

function testGoalInsertion() {
  let inserted = "";
  let cursor = null;
  const editor = {
    getCursor: () => ({ line: 0, ch: 0 }),
    posToOffset: () => 0,
    offsetToPos: (offset) => ({ line: 0, ch: offset }),
    replaceSelection: (value) => { inserted = value; },
    setCursor: (value) => { cursor = value; },
  };
  pluginWithApp().insertGoal(editor);
  assert.equal(
    inserted,
    "> Current Goal: \n>\n> Available Tools: Codex, Browser, Obsidian and any tool useful to the goal.",
  );
  assert.deepEqual(cursor, { line: 0, ch: "> Current Goal: ".length });
}

async function testGoalTrigger() {
  let dispatch = null;
  const state = {
    selection: { main: { empty: true, head: 5 } },
    doc: { length: 5 },
    sliceDoc: (from, to) => "@goal".slice(from, to),
  };
  pluginWithApp().expandGoalTrigger({
    docChanged: true,
    state,
    view: { state, dispatch: (value) => { dispatch = value; } },
  });
  await Promise.resolve();
  assert.equal(dispatch.changes.from, 0);
  assert.equal(dispatch.changes.to, 5);
  assert.ok(dispatch.changes.insert.startsWith("> Current Goal: "));
}

testDailyResolution();
testGoalInsertion();
testGoalTrigger().then(() => console.log("Obsidian integration checks passed."));
