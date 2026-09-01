"use strict";

const { execFile } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { promisify } = require("node:util");
const { EditorView } = require("@codemirror/view");
const { Notice, Plugin, addIcon, moment, normalizePath } = require("obsidian");

const execFileAsync = promisify(execFile);
const DEFAULT_TOOLS = "Codex, Browser, Obsidian and any tool useful to the goal.";
const GOAL_PREFIX = "> Current Goal: ";
const GOAL_TEMPLATE = `${GOAL_PREFIX}\n>\n> Available Tools: ${DEFAULT_TOOLS}`;
const TRIGGER = "@goal";
const GOALWATCH_ICON = `
  <path d="M4 50C15 31 31 23 50 23S85 31 96 50C85 69 69 77 50 77S15 69 4 50Z" fill="none" stroke="currentColor" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="50" cy="50" r="15" fill="none" stroke="currentColor" stroke-width="4"/>
  <path d="M50 23v12M50 65v12M23 50h12M65 50h12" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round"/>
  <circle cx="50" cy="50" r="5" fill="currentColor"/>
`;

class GoalWatchPlugin extends Plugin {
  async onload() {
    this.lastDailyPath = "";
    addIcon("goalwatch-eye", GOALWATCH_ICON);

    this.addCommand({
      id: "use-todays-daily-note",
      name: "Use today's daily note",
      callback: () => this.syncDaily(true),
    });

    this.addCommand({
      id: "use-current-file",
      name: "Use current file",
      callback: () => this.syncCurrentFile(true),
    });

    this.addCommand({
      id: "add-goal",
      name: "Add goal",
      editorCallback: (editor) => this.insertGoal(editor),
    });

    this.registerEvent(
      this.app.workspace.on("file-menu", (menu, file) => {
        if (!file || file.extension !== "md") return;
        menu.addItem((item) => {
          item
            .setTitle("Use this file in GoalWatch")
            .setIcon("goalwatch-eye")
            .onClick(() => this.syncFile(file, true));
        });
      }),
    );

    this.registerEvent(
      this.app.workspace.on("editor-menu", (menu, editor) => {
        menu.addItem((item) => {
          item
            .setTitle("Add GoalWatch goal")
            .setIcon("goalwatch-eye")
            .onClick(() => this.insertGoal(editor));
        });
      }),
    );

    this.registerEditorExtension(
      EditorView.updateListener.of((update) => this.expandGoalTrigger(update)),
    );

    this.app.workspace.onLayoutReady(() => this.syncDaily(false));
    this.registerInterval(window.setInterval(() => this.syncDaily(false), 60_000));
  }

  goalwatchBinary() {
    const binHome = process.env.XDG_BIN_HOME || path.join(os.homedir(), ".local", "bin");
    const configured = path.join(binHome, "goalwatch");
    if (fs.existsSync(configured)) return configured;
    return path.join(os.homedir(), ".local", "bin", "goalwatch");
  }

  vaultPath() {
    const base = this.app.vault.adapter.getBasePath?.();
    if (!base) throw new Error("This vault is not backed by the local filesystem");
    return base;
  }

  dailyInfo() {
    const dailyNotes = this.app.internalPlugins.getPluginById("daily-notes");
    if (!dailyNotes || !dailyNotes.enabled) {
      throw new Error("Obsidian Daily Notes is not enabled");
    }
    const options = dailyNotes.instance?.options || {};
    const dailyDate = moment().format("YYYY-MM-DD");
    const filename = moment().format(options.format || "YYYY-MM-DD") + ".md";
    return {
      dailyDate,
      file: normalizePath([options.folder?.trim(), filename].filter(Boolean).join("/")),
    };
  }

  async runGoalWatch(args) {
    return execFileAsync(this.goalwatchBinary(), args, {
      timeout: 15_000,
      windowsHide: true,
    });
  }

  async syncDaily(showNotice) {
    try {
      const daily = this.dailyInfo();
      if (!showNotice && daily.file === this.lastDailyPath) return;
      await this.runGoalWatch([
        "file",
        "daily",
        "--vault",
        this.vaultPath(),
        "--file",
        daily.file,
        "--date",
        daily.dailyDate,
      ]);
      this.lastDailyPath = daily.file;
      if (showNotice) new Notice(`GoalWatch now follows ${daily.file}`);
    } catch (error) {
      if (showNotice) {
        console.error("GoalWatch: daily-note synchronization failed", error);
        new Notice(`GoalWatch could not use today's daily note: ${error.message}`);
      }
    }
  }

  async syncFile(file, showNotice) {
    try {
      if (!file || file.extension !== "md") throw new Error("Open a Markdown file first");
      await this.runGoalWatch([
        "file",
        "current",
        "--vault",
        this.vaultPath(),
        "--file",
        file.path,
      ]);
      if (showNotice) new Notice(`GoalWatch now uses ${file.path} for today`);
    } catch (error) {
      console.error("GoalWatch: current-file synchronization failed", error);
      if (showNotice) new Notice(`GoalWatch could not use the current file: ${error.message}`);
    }
  }

  async syncCurrentFile(showNotice) {
    return this.syncFile(this.app.workspace.getActiveFile(), showNotice);
  }

  insertGoal(editor) {
    if (!editor) {
      new Notice("Open a Markdown editor before adding a goal");
      return;
    }
    const from = editor.getCursor("from");
    const startOffset = editor.posToOffset(from);
    editor.replaceSelection(GOAL_TEMPLATE);
    editor.setCursor(editor.offsetToPos(startOffset + GOAL_PREFIX.length));
  }

  expandGoalTrigger(update) {
    if (!update.docChanged) return;
    const range = update.state.selection.main;
    if (!range.empty) return;
    const to = range.head;
    if (to < TRIGGER.length || update.state.sliceDoc(to - TRIGGER.length, to) !== TRIGGER) return;
    const from = to - TRIGGER.length;
    queueMicrotask(() => {
      const view = update.view;
      if (to > view.state.doc.length || view.state.sliceDoc(from, to) !== TRIGGER) return;
      view.dispatch({
        changes: { from, to, insert: GOAL_TEMPLATE },
        selection: { anchor: from + GOAL_PREFIX.length },
      });
    });
  }
}

module.exports = GoalWatchPlugin;
