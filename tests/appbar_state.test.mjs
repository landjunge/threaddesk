import { readFileSync } from "node:fs";
import assert from "node:assert/strict";
import test from "node:test";
const source = readFileSync(new URL("../src/threaddesk/ui/static/networkpunkt-appbar-state.js", import.meta.url));
const { createPeerState } = await import(`data:text/javascript;base64,${source.toString("base64")}`);
const expected = { appId:"4allpass", connectionRef:"fixture-link", peerRef:"fixture-peer", peerEpoch:"epoch-1",
  unlockScope:{ userRef:"fixture-user", vaultRef:"fixture-vault" } };
function setup(appId="4allpass") {
  let time=0, wall=100000;
  const peer=createPeerState({ ...expected, appId }, { clock:()=>time, wallClock:()=>wall });
  const observation = patch => ({ v:1,appId,connectionRef:"fixture-link",peerRef:"fixture-peer",peerEpoch:"epoch-1",
    seq:0,state:"confirmed",ttlMs:15000,...patch });
  return {peer, observation, advance(ms){time+=ms;wall+=ms;}, rollback(){wall--;}};
}
const unlocked = {userRef:"fixture-user",vaultRef:"fixture-vault",allowed:true,state:"unlocked",ttlMs:1000};
test("unknown and connecting are distinct; only a fresh matching reply confirms",()=>{
  const x=setup();assert.equal(x.peer.snapshot().state,"unknown");const t=x.peer.begin();
  assert.equal(x.peer.begin(),t);assert.equal(x.peer.snapshot().state,"connecting");
  assert.equal(x.peer.receive(t,x.observation()),true);assert.equal(x.peer.snapshot().state,"confirmed");
  x.advance(15000);assert.deepEqual(x.peer.snapshot(),{state:"unknown",vault:"unknown",pulse:false});
});
for(const [key,value] of [["v",2],["appId","threaddesk"],["connectionRef","wrong"],["peerRef","wrong"],["peerEpoch","old"],
  ["seq",-1],["seq",1.1],["seq",Number.MAX_SAFE_INTEGER+1],["state","live"],["ttlMs",15001],["ttlMs",0],["ttlMs",NaN],["ttlMs",Infinity],["ttlMs","1000"],["authenticated",true],["pid",123]]) {
  test(`invalid or mismatched ${key}=${value} stays neutral`,()=>{const x=setup();assert.equal(x.peer.receive(x.peer.begin(),x.observation({[key]:value})),false);assert.equal(x.peer.snapshot().state,"unknown");});
}
test("deadline, local wall-clock rollback and delayed replies fail closed",()=>{
  const x=setup();let t=x.peer.begin();x.advance(2000);assert.equal(x.peer.receive(t,x.observation()),false);
  t=x.peer.begin();assert(x.peer.receive(t,x.observation({vault:unlocked})));x.rollback();assert.equal(x.peer.snapshot().pulse,false);
});
test("a new check preserves a fresh ring, timeout removes it",()=>{
  const x=setup();x.peer.receive(x.peer.begin(),x.observation());x.peer.begin();assert.equal(x.peer.snapshot().state,"confirmed");
  x.advance(2000);assert.equal(x.peer.snapshot().state,"unknown");
});
test("old generation, epoch, sequence and visibility invalidation cannot reconnect",()=>{
  const x=setup();const old=x.peer.begin();x.peer.reset({...expected,peerEpoch:"epoch-2"});
  assert.equal(x.peer.receive(old,x.observation()),false);
  assert.equal(x.peer.receive(x.peer.begin(),x.observation()),false);
  assert(x.peer.receive(x.peer.begin(),x.observation({peerEpoch:"epoch-2",seq:10})));
  assert.equal(x.peer.receive(x.peer.begin(),x.observation({peerEpoch:"epoch-2",seq:9})),false);
  const t=x.peer.begin();x.peer.invalidate();assert.equal(x.peer.receive(t,x.observation({peerEpoch:"epoch-2",seq:11})),false);
});
test("AP4 unlock has separate shorter freshness; locked and unknown remain distinct",()=>{
  const x=setup();x.peer.receive(x.peer.begin(),x.observation({vault:unlocked}));assert.equal(x.peer.snapshot().pulse,true);
  x.advance(1000);assert.deepEqual(x.peer.snapshot(),{state:"confirmed",vault:"unknown",pulse:false});
  x.peer.receive(x.peer.begin(),x.observation({seq:1,vault:{...unlocked,state:"locked"}}));
  assert.deepEqual(x.peer.snapshot(),{state:"confirmed",vault:"locked",pulse:false});
});
for(const patch of [{allowed:false},{allowed:"true"},{userRef:"another-user"},{vaultRef:"another-vault"},{ttlMs:20000},{state:"active"},{secret:"not-accepted"}]) {
  test(`unapproved or malformed unlock scope ${Object.keys(patch)} never pulses`,()=>{
    const x=setup();x.peer.receive(x.peer.begin(),x.observation({vault:{...unlocked,...patch}}));
    assert.deepEqual(x.peer.snapshot(),{state:"confirmed",vault:"unknown",pulse:false});
  });
}
for(const appId of ["kirabridge","threaddesk","tollgate"]) test(`${appId} never has an activity/unlock pulse`,()=>{
  const x=setup(appId);x.peer.receive(x.peer.begin(),x.observation({vault:unlocked}));assert.equal(x.peer.snapshot().pulse,false);
});
test("failure and explicit disconnect remove ring; reconnect needs another accepted reply",()=>{
  const x=setup();x.peer.receive(x.peer.begin(),x.observation({vault:unlocked}));x.peer.fail(x.peer.begin(),"error");
  assert.equal(x.peer.snapshot().state,"error");assert.equal(x.peer.snapshot().pulse,false);
  x.peer.receive(x.peer.begin(),x.observation({seq:1,state:"disconnected"}));assert.equal(x.peer.snapshot().state,"disconnected");
  x.peer.begin();assert.equal(x.peer.snapshot().state,"connecting");
  x.peer.receive(x.peer.begin(),x.observation({seq:2}));assert.equal(x.peer.snapshot().state,"confirmed");
});
