from __future__ import annotations
import json, tempfile, threading, unittest
from pathlib import Path
from chat.conversation_store import ConversationStore

class TestConversationStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = ConversationStore(self.root)

    def tearDown(self): self.tmp.cleanup()

    def test_create_and_list(self):
        cid=self.store.create_conversation("Проверка")
        self.assertEqual(self.store.get_meta(cid)["title"],"Проверка")
        self.assertEqual(self.store.list_conversations()[0]["conversation_id"],cid)

    def test_append_and_read(self):
        cid=self.store.create_conversation()
        for n in range(3): self.store.append_event(cid,"user_message",{"text":str(n)})
        self.assertEqual([x["sequence"] for x in self.store.read_all(cid)],[1,2,3])

    def test_read_after(self):
        cid=self.store.create_conversation()
        for n in range(4): self.store.append_event(cid,"user_message",{"text":str(n)})
        self.assertEqual([x["sequence"] for x in self.store.read_after(cid,2)],[3,4])

    def test_sequence_restored_after_restart(self):
        cid=self.store.create_conversation()
        self.store.append_event(cid,"thinking",{})
        restarted=ConversationStore(self.root)
        self.assertEqual(restarted.append_event(cid,"thinking",{})["sequence"],2)

    def test_concurrent_append(self):
        cid=self.store.create_conversation()
        def worker(i):
            for n in range(10): self.store.append_event(cid,"test",{"i":i,"n":n})
        threads=[threading.Thread(target=worker,args=(i,)) for i in range(10)]
        [t.start() for t in threads]; [t.join() for t in threads]
        seq=[e["sequence"] for e in self.store.read_all(cid)]
        self.assertEqual(len(seq),100); self.assertEqual(seq,list(range(1,101)))

    def test_truncated_tail(self):
        cid=self.store.create_conversation()
        self.store.append_event(cid,"ok",{"n":1})
        path=self.root/cid/"events.jsonl"
        with path.open("ab") as f: f.write(b'{"sequence":2,"type":')
        restarted=ConversationStore(self.root)
        self.assertEqual([e["sequence"] for e in restarted.read_all(cid)],[1])
        self.assertTrue(path.read_bytes().endswith(b"\n"))

    def test_verification_gate(self):
        cid=self.store.create_conversation()
        task="task_1"
        self.assertFalse(self.store.has_recent_verification(cid,task))
        self.store.append_event(cid,"verification",{"checks":[{"name":"tests","status":"passed"}],"verified":True},task_id=task)
        self.assertTrue(self.store.has_recent_verification(cid,task))
        self.store.append_event(cid,"turn_completed",{"status":"completed"},task_id=task)
        self.assertFalse(self.store.has_recent_verification(cid,task))

    def test_verification_is_scoped_to_task_and_false_result_blocks_gate(self):
        cid=self.store.create_conversation()
        self.store.append_event(cid,"verification",{"verified":True},task_id="task_a")
        self.assertFalse(self.store.has_recent_verification(cid,"task_b"))
        self.store.append_event(cid,"verification",{"verified":False},task_id="task_a")
        self.assertFalse(self.store.has_recent_verification(cid,"task_a"))

    def test_approval_lifecycle(self):
        cid=self.store.create_conversation()
        aid=self.store.create_approval(cid,"task_x","call_x","write_file",{"path":"a"},"Нужно разрешение")
        self.assertEqual(self.store.get_approval(cid,aid)["status"],"pending")
        first=self.store.resolve_approval(cid,aid,"approved")
        second=self.store.resolve_approval(cid,aid,"approved")
        self.assertEqual(first["resolved_at"],second["resolved_at"])
        with self.assertRaises(ValueError): self.store.resolve_approval(cid,aid,"maybe")

    def test_pending_approvals(self):
        cid=self.store.create_conversation()
        a=self.store.create_approval(cid,"t","c1","write_file",{},"1")
        self.store.create_approval(cid,"t","c2","delete_file",{},"2")
        self.store.resolve_approval(cid,a,"rejected")
        self.assertEqual(len(self.store.list_pending_approvals(cid)),1)

if __name__=="__main__": unittest.main()
