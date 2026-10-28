import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import server

class AgentRuntimeTests(unittest.TestCase):
    def test_agent_loop_executes_only_granted_tools_and_returns_final_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            workspace=root/'workspace'; workspace.mkdir()
            (workspace/'brief.txt').write_text('Approved project brief',encoding='utf-8')
            data=root/'data'; data.mkdir()
            server.write_json(data/'permissions.json',{'local_files':True,'roots':[str(workspace)]})
            responses=[
                {'model':'test-model','message':{'role':'assistant','content':'','tool_calls':[{'function':{'name':'read_file','arguments':{'path':str(workspace/'brief.txt')}}}]}},
                {'model':'test-model','message':{'role':'assistant','content':'Прочитал brief.txt и подготовил ответ.'}}
            ]
            with patch.object(server,'DATA',data), patch.object(server,'ollama_request',side_effect=responses) as request:
                result=server.run_agent_task('test-model',{'title':'Прочитать brief','description':'Изучи краткое описание.'},{'id':'agent1','name':'Reader','role':'ANALYST','system_prompt':'Будь точен.','permissions':{'file_loading':True}},None)
            self.assertEqual(result['tool_calls'],1)
            self.assertIn('Прочитал brief.txt',result['response'])
            self.assertEqual(request.call_count,2)
            tool_payload=request.call_args_list[0].args[1]
            self.assertIn('read_file',{x['function']['name'] for x in tool_payload['tools']})
            final_messages=request.call_args_list[1].args[1]['messages']
            self.assertTrue(any(x.get('role')=='tool' and 'Approved project brief' in x.get('content','') for x in final_messages))

    def test_team_workflow_passes_manager_plan_to_specialist_and_result_to_qa(self):
        """Проверяет реальный 5-стадийный контракт run_agent_team:

        1. MANAGER → DISPATCHER (delegate с планом)
        2. DISPATCHER → workers (dispatch с tasks)
        3. worker (CODER) — исполнение
        4. DISPATCHER → MANAGER (report со сводкой)
        5. MANAGER → финал (done + final_answer)

        Mock возвращает валидный JSON на каждой стадии, как этого ждёт
        parse_orchestrator_decision в server.py.
        """
        results = [
            # Stage 1: MANAGER делегирует Диспетчеру
            {'response': '{"action":"delegate","target":"DISPATCHER","instruction":"Разбить на подзадачи"}',
             'tool_calls': 0, 'model': 'model-a'},
            # Stage 2: DISPATCHER раздаёт задачи специалистам
            {'response': '{"tasks":[{"role":"CODER","task":"Реализовать компонент"}]}',
             'tool_calls': 0, 'model': 'model-a'},
            # Stage 3: CODER исполняет
            {'response': 'Компонент реализован. Изменён файл component.py.',
             'tool_calls': 2, 'model': 'model-b'},
            # Stage 4: DISPATCHER собирает сводку для MANAGER
            {'response': '{"action":"report","target":"MANAGER","summary":"Компонент реализован, готов к проверке"}',
             'tool_calls': 0, 'model': 'model-a'},
            # Stage 5: MANAGER принимает финальное решение
            {'response': '{"done":true,"final_answer":"Задача выполнена: компонент реализован."}',
             'tool_calls': 0, 'model': 'model-a'},
        ]
        task = {'title': 'Собрать компонент', 'description': 'Реализовать и проверить компонент.'}
        specialist = {
            'id': 'coder1', 'name': 'Разработчик', 'role': 'CODER', 'model': 'model-b',
            'system_prompt': 'Пиши качественный код.', 'permissions': {},
        }

        with patch.object(server, 'run_agent_task', side_effect=results) as run:
            result = server.run_agent_team(
                'model-a', task, specialist,
                {'name': 'Demo', 'description': 'Context', 'path': ''},
            )

        # 5 вызовов: MANAGER, DISPATCHER, CODER, DISPATCHER, MANAGER
        self.assertEqual(run.call_count, 5)

        # Итоговый ответ — из финального решения MANAGER
        self.assertEqual(result['response'], 'Задача выполнена: компонент реализован.')

        # tool_calls аккумулируются из всех стадий
        self.assertEqual(result['tool_calls'], 2)

        # Порядок ролей в team_result
        roles = [stage['role'] for stage in result['team_result']]
        self.assertEqual(roles, ['MANAGER', 'DISPATCHER', 'CODER', 'DISPATCHER', 'MANAGER'])

        # Проверка, что план MANAGER дошёл до DISPATCHER
        dispatcher_call = run.call_args_list[1]
        dispatcher_desc = dispatcher_call.args[1]['description']
        self.assertIn('Разбить на подзадачи', dispatcher_desc)

        # Проверка, что сводка DISPATCHER дошла до MANAGER (в 5-й стадии)
        final_call = run.call_args_list[4]
        final_desc = final_call.args[1]['description']
        self.assertIn('Компонент реализован, готов к проверке', final_desc)

    def test_agent_loop_does_not_offer_file_tools_without_global_permission(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); data=root/'data'; data.mkdir()
            server.write_json(data/'permissions.json',{'local_files':False,'roots':[str(root)]})
            with patch.object(server,'DATA',data), patch.object(server,'ollama_request',return_value={'model':'test','response':'plain answer'}) as request:
                result=server.run_agent_task('test',{'title':'Question','description':'Answer'},{'id':'agent1','role':'ANALYST','permissions':{'file_loading':True}},None)
            self.assertEqual(result['tool_calls'],0)
            self.assertEqual(request.call_count,1)
            self.assertEqual(request.call_args.args[0],'/api/generate')
            self.assertNotIn('tools',request.call_args.args[1])

if __name__=='__main__':
    unittest.main()
