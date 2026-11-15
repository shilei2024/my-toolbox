import assert from "node:assert/strict";
import test from "node:test";
import { createHmac } from "node:crypto";
import { accountSessionCheck } from "../src/gallery/account-session-check.ts";
import { InternalViewerContextCodec } from "../src/gallery/internal-auth.ts";
import type { Pool } from "pg";

test("revocable signed context carries session identity and rejects missing or revoked sessions", async () => {
  const secret="test-shared-secret-for-account-sessions";
  const payload={v:2,role:"user",userId:1,authEpoch:2,sessionRef:"a".repeat(64),
    requestId:"11111111-1111-4111-8111-111111111111",issuedAt:100,expiresAt:160};
  const context=Buffer.from(JSON.stringify(payload)).toString("base64url");
  const signature=createHmac("sha256",secret).update(context).digest("base64url");
  const viewer=new InternalViewerContextCodec(secret,300,()=>110).verify({"x-mavis-user-context":context,"x-mavis-user-signature":signature});
  assert.equal(viewer.authEpoch,2);assert.equal(viewer.sessionRef,payload.sessionRef);
  let rows: {is_admin:boolean}[]=[{is_admin:false}];
  const pool={query:async (_sql:string,params:unknown[])=>{assert.deepEqual(params,[1,2,payload.sessionRef]);return {rows};}} as unknown as Pick<Pool,"query">;
  const check=accountSessionCheck(pool);
  await check(viewer);
  await assert.rejects(check({...viewer,role:"admin"}));
  rows=[];await assert.rejects(check(viewer));
  await assert.rejects(check({role:"user",userId:1,requestId:payload.requestId}));
  await check({role:"guest",requestId:payload.requestId});
});
