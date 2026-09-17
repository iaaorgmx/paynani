// Contract tests for the paynani OpenCode plugin. Runs under `node --test` and
// `bun test`; scripts/test_opencode_plugin.py picks whichever is installed.
//
// The plugin's decisions are what is tested here, against a fake OpenCode
// client and a fake session_start.py. The spool, offset and lock themselves are
// tested in scripts/test_opencode.py.

import assert from "node:assert/strict"
import { test } from "node:test"

import { createPaynani, shouldRun } from "./paynani.js"

function fakeClient({ promptResult = {}, promptThrows = null } = {}) {
  const calls = { prompts: [], logs: [], toasts: [] }
  const client = {
    app: { log: async ({ body }) => calls.logs.push(body) },
    tui: { showToast: async ({ body }) => calls.toasts.push(body) },
    session: {
      promptAsync: async (options) => {
        calls.prompts.push(options)
        if (promptThrows) throw promptThrows
        return promptResult
      },
    },
  }
  return { client, calls }
}

function fakeRun({ owner = true, pending = null, ack = { offset: 0 } } = {}) {
  const calls = []
  const run = async (args) => {
    calls.push(args)
    if (args[0] === "--opencode-claim") return { owner, holder: owner ? 42 : 7 }
    if (args[0] === "--opencode-pending") {
      return pending ?? { through: 0, count: 0, capped: false, prompt: "", system: "" }
    }
    if (args[0] === "--opencode-ack") return ack
    if (args[0] === "--opencode-release") return { released: true }
    return null
  }
  return { run, calls }
}

const PENDING = {
  through: 128,
  count: 1,
  capped: false,
  prompt: "Procesa el evento paynani imap:INBOX:1:5 del journal.",
  system: "",
}

async function withTarget(paynani, sessionID = "ses_root") {
  await paynani.hooks["chat.message"]({ sessionID })
  return sessionID
}

test("nothing is sent before a person has used a session", async () => {
  const { client, calls } = fakeClient()
  const { run, calls: runs } = fakeRun({ pending: PENDING })
  const paynani = createPaynani({ client, run, pid: 42 })
  await paynani.tick()
  assert.equal(calls.prompts.length, 0)
  assert.equal(runs.length, 0)
})

test("pending events go to the target session and are acknowledged at the exact offset", async () => {
  const { client, calls } = fakeClient()
  const { run, calls: runs } = fakeRun({ pending: PENDING })
  const paynani = createPaynani({ client, run, pid: 42 })
  const target = await withTarget(paynani)
  await paynani.tick()
  assert.equal(calls.prompts.length, 1)
  assert.equal(calls.prompts[0].path.id, target)
  assert.deepEqual(calls.prompts[0].body.parts, [{ type: "text", text: PENDING.prompt }])
  assert.deepEqual(runs.at(-1), ["--opencode-ack", "128"])
})

test("a refused prompt is not acknowledged", async () => {
  const { client } = fakeClient({ promptResult: { error: { name: "BadRequest" } } })
  const { run, calls: runs } = fakeRun({ pending: PENDING })
  const paynani = createPaynani({ client, run, pid: 42 })
  await withTarget(paynani)
  await paynani.tick()
  assert.equal(runs.some((args) => args[0] === "--opencode-ack"), false)
})

test("a prompt that throws is not acknowledged and does not escape", async () => {
  const { client } = fakeClient({ promptThrows: new Error("connection refused") })
  const { run, calls: runs } = fakeRun({ pending: PENDING })
  const paynani = createPaynani({ client, run, pid: 42 })
  await withTarget(paynani)
  await paynani.tick()
  assert.equal(runs.some((args) => args[0] === "--opencode-ack"), false)
})

test("a plugin that does not hold the lock delivers nothing", async () => {
  const { client, calls } = fakeClient()
  const { run, calls: runs } = fakeRun({ owner: false, pending: PENDING })
  const paynani = createPaynani({ client, run, pid: 42 })
  await withTarget(paynani)
  await paynani.tick()
  assert.equal(calls.prompts.length, 0)
  assert.equal(runs.some((args) => args[0] === "--opencode-pending"), false)
})

test("a busy session is left alone until it goes idle", async () => {
  const { client, calls } = fakeClient()
  const { run } = fakeRun({ pending: PENDING })
  const paynani = createPaynani({ client, run, pid: 42 })
  const target = await withTarget(paynani)
  await paynani.hooks.event({
    event: { type: "session.status", properties: { sessionID: target, status: { type: "busy" } } },
  })
  await paynani.tick()
  assert.equal(calls.prompts.length, 0)
  await paynani.hooks.event({ event: { type: "session.idle", properties: { sessionID: target } } })
  assert.equal(calls.prompts.length, 1)
})

test("a subagent session never becomes the target", async () => {
  const { client, calls } = fakeClient()
  const { run } = fakeRun({ pending: PENDING })
  const paynani = createPaynani({ client, run, pid: 42 })
  await withTarget(paynani, "ses_root")
  await paynani.hooks.event({
    event: { type: "session.created", properties: { info: { id: "ses_child", parentID: "ses_root" } } },
  })
  await paynani.hooks["chat.message"]({ sessionID: "ses_child" })
  await paynani.tick()
  assert.equal(calls.prompts[0].path.id, "ses_root")
})

test("service problems are shown once, not sent as a prompt", async () => {
  const { client, calls } = fakeClient()
  const { run, calls: runs } = fakeRun({
    pending: { ...PENDING, prompt: "", count: 0, system: "Mail listener is DOWN" },
  })
  const paynani = createPaynani({ client, run, pid: 42 })
  await withTarget(paynani)
  await paynani.tick()
  await paynani.tick()
  assert.equal(calls.prompts.length, 0)
  assert.equal(calls.toasts.length, 1)
  assert.equal(calls.toasts[0].message, "Mail listener is DOWN")
  const statusAsks = runs.filter((args) => args[0] === "--opencode-pending" && args.includes("--status"))
  assert.equal(statusAsks.length, 1)
})

test("dispose releases the lock only when this plugin held it", async () => {
  const held = fakeRun({ pending: PENDING })
  const owner = createPaynani({ client: fakeClient().client, run: held.run, pid: 42 })
  await withTarget(owner)
  await owner.tick()
  await owner.dispose()
  assert.ok(held.calls.some((args) => args[0] === "--opencode-release" && args[1] === "42"))

  const other = fakeRun({ owner: false })
  const bystander = createPaynani({ client: fakeClient().client, run: other.run, pid: 43 })
  await withTarget(bystander)
  await bystander.tick()
  await bystander.dispose()
  assert.equal(other.calls.some((args) => args[0] === "--opencode-release"), false)
})

test("dispose always forgets this process's presence, lock or not", async () => {
  const held = fakeRun({ pending: PENDING })
  const owner = createPaynani({ client: fakeClient().client, run: held.run, pid: 42 })
  await withTarget(owner)
  await owner.tick()
  await owner.dispose()
  assert.deepEqual(held.calls.slice(-2), [["--opencode-release", "42"], ["--opencode-bye", "42"]])

  const idle = fakeRun()
  const opened = createPaynani({ client: fakeClient().client, run: idle.run, pid: 43 })
  await opened.dispose()
  assert.deepEqual(idle.calls, [["--opencode-bye", "43"]])
})

test("the plugin stays out of one-shot runs and can be turned off", () => {
  assert.equal(shouldRun(["opencode"], {}), true)
  assert.equal(shouldRun(["opencode", "--port", "4096"], {}), true)
  assert.equal(shouldRun(["/usr/bin/bun", "opencode", "run", "hi"], {}), false)
  assert.equal(shouldRun(["opencode", "run", "hi"], {}), false)
  assert.equal(shouldRun(["opencode"], { PAYNANI_OPENCODE_DISABLE: "1" }), false)
})
