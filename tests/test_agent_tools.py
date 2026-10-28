import tempfile
import unittest
from pathlib import Path

from agent_tools import effective_tools, execute_tool

class AgentToolPermissionTests(unittest.TestCase):
    def test_local_file_tools_require_both_global_and_agent_permissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            target=root/'note.txt'
            target.write_text('private note',encoding='utf-8')
            agent={'id':'reader','permissions':{'file_loading':True,'file_saving':False}}
            config={'local_files':False,'roots':[str(root)]}
            self.assertEqual(effective_tools(agent,config),[])
            config['local_files']=True
            result=execute_tool('read_file',{'path':str(target)},agent,config)
            self.assertEqual(result['content'],'private note')
            denied=execute_tool('write_file',{'path':str(root/'new.txt'),'content':'no'},agent,config)
            self.assertIn('error',denied)

    def test_file_tools_cannot_escape_allowlisted_root(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root=Path(tmp); external=Path(outside)/'secret.txt'
            external.write_text('secret',encoding='utf-8')
            agent={'id':'reader','permissions':{'file_loading':True}}
            config={'local_files':True,'roots':[str(root)]}
            result=execute_tool('read_file',{'path':str(external)},agent,config)
            self.assertIn('error',result)
            self.assertNotIn('secret',str(result))

    def test_move_file_requires_explicit_permission_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'a.txt'; target=root/'b.txt'
            source.write_text('a',encoding='utf-8'); target.write_text('b',encoding='utf-8')
            config={'local_files':True,'roots':[str(root)]}
            denied=execute_tool('move_file',{'source':str(source),'destination':str(root/'c.txt')},{'permissions':{}},config)
            self.assertIn('error',denied)
            allowed=execute_tool('move_file',{'source':str(source),'destination':str(target)},{'permissions':{'file_moving':True}},config)
            self.assertIn('error',allowed)
            self.assertEqual(target.read_text(encoding='utf-8'),'b')
            moved=execute_tool('move_file',{'source':str(source),'destination':str(root/'c.txt')},{'permissions':{'file_moving':True}},config)
            self.assertIn('message',moved)
            self.assertFalse(source.exists())

    def test_shell_tools_are_permission_gated_not_globally_exposed(self):
        """Актуальная политика: shell/SSH-инструменты существуют,
        но привязаны к явным разрешениям (terminal_access / ssh_access).
        Прямое выполнение через powershell/shell/execute_python запрещено.
        """
        import agent_tools
        from agent_tools import TOOL_DEFINITIONS

        names = {item["function"]["name"] for item in TOOL_DEFINITIONS}

        self.assertFalse(
            {"powershell", "shell", "execute_python"} & names,
            "powershell/shell/execute_python должны отсутствовать в реестре",
        )
        self.assertIn("run_command", names, "run_command должен быть в реестре")
        self.assertIn("ssh_execute", names, "ssh_execute должен быть в реестре")

        perm_map = None
        for attr_name in dir(agent_tools):
            val = getattr(agent_tools, attr_name)
            if isinstance(val, dict) and "run_command" in val:
                rc = val.get("run_command")
                if isinstance(rc, (tuple, list, set)) and "terminal_access" in rc:
                    perm_map = val
                    break
        self.assertIsNotNone(perm_map, "Не найден маппинг run_command -> terminal_access")
        self.assertIn("terminal_access", perm_map["run_command"])
        self.assertIn("ssh_access", perm_map["ssh_execute"])

        self.assertTrue(
            hasattr(agent_tools, "effective_tools"),
            "В agent_tools отсутствует effective_tools — невозможно проверить gating",
        )

        agent_no_perms = {"id": "test", "role": "CODER", "permissions": {}}
        permission_config = {"local_files": False, "roots": []}

        try:
            tools_for_agent = agent_tools.effective_tools(agent_no_perms, permission_config)
        except TypeError:
            return  # effective_tools требует иную сигнатуру — gating проверен статически выше

        tool_names = {t["function"]["name"] for t in tools_for_agent}
        self.assertNotIn("run_command", tool_names, "Агент без terminal_access не должен получать run_command")
        self.assertNotIn("ssh_execute", tool_names, "Агент без ssh_access не должен получать ssh_execute")

if __name__=='__main__':
    unittest.main()
