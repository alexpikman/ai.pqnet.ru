import json, os, tempfile, unittest
from unittest.mock import patch
from pathlib import Path
import server

class StorageTests(unittest.TestCase):
    def test_agent_permissions_ignore_unsupported_legacy_keys(self):
        permissions = server._normalize_agent_permissions({'file_loading': True, 'legacy_read': True})
        self.assertTrue(permissions['file_loading'])
        self.assertFalse(permissions['file_saving'])
        self.assertEqual(set(permissions), server.AGENT_PERMISSION_KEYS)
        self.assertNotIn('legacy_read', permissions)

    def test_agent_permissions_reject_non_object_values(self):
        with self.assertRaisesRegex(ValueError, 'permissions'):
            server._normalize_agent_permissions(['file_loading'])

    def test_default_settings_have_header_and_appearance(self):
        self.assertIn('appearance', server.DEFAULT_SETTINGS)
        self.assertIn('header', server.DEFAULT_SETTINGS)
    def test_default_pages_include_core_sections(self):
        ids={p['id'] for p in server.DEFAULT_PAGES}
        self.assertTrue({'dashboard','interface-settings','pages','github','system-log','menu-builder','modules','diagnostics','models','agents','projects','tasks'}.issubset(ids))
    def test_header_spacing_defaults_exist(self):
        self.assertEqual(server.DEFAULT_SETTINGS['header']['paddingTop'], 24)
        self.assertEqual(server.DEFAULT_SETTINGS['header']['paddingRight'], 22)
        self.assertEqual(server.DEFAULT_SETTINGS['header']['paddingBottom'], 24)
    def test_module_contract_schema_is_tracked(self):
        self.assertTrue((server.ROOT / 'module-contract.schema.json').exists())
    def test_module_directory_is_defined(self):
        self.assertEqual(server.MODULES, server.ROOT / 'modules')
    def test_agent_tool_runtime_is_tracked(self):
        self.assertTrue((server.ROOT / 'agent_tools.py').exists())
    def test_slug_is_safe(self):
        import re
        slug=re.sub(r'[^a-z0-9-]+','-','my page / hello').strip('-')
        self.assertEqual(slug,'my-page-hello')


class ModuleRuntimeTests(unittest.TestCase):
    def test_graph_executes_builtin_transform_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            modules=[
                {'id':'source','name':'Источник','manifest':{'runtime':{'kind':'input'}}},
                {'id':'upper','name':'В верхний регистр','manifest':{'runtime':{'kind':'transform','operation':'uppercase'}}},
                {'id':'finish','name':'Выход','manifest':{'runtime':{'kind':'output'}}}
            ]
            registry={'modules':modules,'connections':[{'from':'source','to':'upper','label':'text'},{'from':'upper','to':'finish','label':'text'}]}
            with patch.object(server,'DATA',root), patch.object(server,'MODULES',root/'modules'):
                (root/'modules').mkdir()
                server.write_json(root/'modules.json',registry)
                result=server.execute_module_graph({'start_id':'source','input':'hello pqlocal'})
            self.assertTrue(result['ok'])
            self.assertEqual(result['executed'],3)
            self.assertEqual(result['result'],'HELLO PQLOCAL')
            self.assertEqual(result['order'],['source','upper','finish'])

    def test_graph_routes_values_through_named_ports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            modules=[
                {'id':'source','name':'Источник','manifest':{'runtime':{'kind':'input'},'inputs':[],'outputs':[{'name':'prompt','type':'text'}]}},
                {'id':'template','name':'Шаблон','manifest':{'runtime':{'kind':'template','template':'Prompt: {input.message}'},'inputs':[{'name':'message','type':'text'}],'outputs':[{'name':'result','type':'text'}]}},
                {'id':'finish','name':'Выход','manifest':{'runtime':{'kind':'output'},'inputs':[{'name':'input','type':'text'}],'outputs':[{'name':'output','type':'text'}]}}
            ]
            registry={'modules':modules,'connections':[{'from':'source','to':'template','from_port':'prompt','to_port':'message'},{'from':'template','to':'finish','from_port':'result','to_port':'input'}]}
            with patch.object(server,'DATA',root), patch.object(server,'MODULES',root/'modules'):
                (root/'modules').mkdir()
                server.write_json(root/'modules.json',registry)
                result=server.execute_module_graph({'start_id':'source','input':'hello'})
            self.assertEqual(result['result'],'Prompt: hello')

    def test_connection_validator_rejects_cycles(self):
        current={'modules':[{'id':'a','name':'A','manifest':{}},{'id':'b','name':'B','manifest':{}}]}
        with self.assertRaisesRegex(ValueError,'Циклические связи запрещены'):
            server.validate_module_connections(current,[{'from':'a','to':'b'},{'from':'b','to':'a'}])

    def test_connection_validator_allows_distinct_ports_between_same_modules(self):
        current={'modules':[
            {'id':'source','name':'Источник','manifest':{'outputs':[{'name':'one','type':'text'},{'name':'two','type':'text'}]}},
            {'id':'target','name':'Цель','manifest':{'inputs':[{'name':'first','type':'text'},{'name':'second','type':'text'}]}}
        ]}
        links=server.validate_module_connections(current,[
            {'from':'source','from_port':'one','to':'target','to_port':'first'},
            {'from':'source','from_port':'two','to':'target','to_port':'second'}
        ])
        self.assertEqual(len(links),2)

    def test_connection_validator_rejects_incompatible_port_types(self):
        current={'modules':[
            {'id':'source','name':'Источник','manifest':{'outputs':[{'name':'payload','type':'json'}]}},
            {'id':'target','name':'Цель','manifest':{'inputs':[{'name':'text','type':'text'}]}}
        ]}
        with self.assertRaisesRegex(ValueError,'Несовместимые типы портов'):
            server.validate_module_connections(current,[{'from':'source','to':'target','from_port':'payload','to_port':'text'}])

    def test_graph_rejects_unconfigured_external_module(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            registry={'modules':[{'id':'external','name':'Внешний','manifest':{'api_version':'1.0'}}],'connections':[]}
            with patch.object(server,'DATA',root), patch.object(server,'MODULES',root/'modules'):
                server.write_json(root/'modules.json',registry)
                with self.assertRaisesRegex(ValueError,'не имеет разрешённого встроенного типа'):
                    server.execute_module_graph({'start_id':'external','input':'test'})


class ChatProviderTests(unittest.TestCase):
    def test_provider_is_inferred_from_claude_model_name(self):
        providers=[
            {'id':'ollama','name':'Ollama','kind':'local','format':'ollama','base_url':'http://127.0.0.1:11434'},
            {'id':'anthropic','name':'Anthropic','kind':'cloud','format':'anthropic','base_url':'https://api.anthropic.com/v1','api_key':'test-key'}
        ]
        with patch.object(server,'provider_items',return_value=providers):
            self.assertEqual(server.provider_for_model('claude-sonnet-5')['id'],'anthropic')

    def test_deepseek_model_uses_single_configured_custom_cloud_provider(self):
        providers=[
            {'id':'ollama','name':'Ollama','kind':'local','format':'ollama','base_url':'http://127.0.0.1:11434'},
            {'id':'fastypass','name':'FastBypass','kind':'cloud','format':'openai','base_url':'https://api.fastypass.com/v1','api_key':'test-key'}
        ]
        with patch.object(server,'provider_items',return_value=providers):
            self.assertEqual(server.provider_for_model('deepseek-flash')['id'],'fastypass')

    def test_known_local_model_still_uses_ollama(self):
        providers=[
            {'id':'ollama','name':'Ollama','kind':'local','format':'ollama','base_url':'http://127.0.0.1:11434'},
            {'id':'fastypass','name':'FastBypass','kind':'cloud','format':'openai','base_url':'https://api.fastypass.com/v1','api_key':'test-key'}
        ]
        with patch.object(server,'provider_items',return_value=providers):
            self.assertEqual(server.provider_for_model('qwen3.5:4b')['id'],'ollama')

    def test_anthropic_request_uses_messages_api_and_parses_text(self):
        import io
        provider={'id':'anthropic','name':'Anthropic','kind':'cloud','format':'anthropic','base_url':'https://api.example.test/v1','api_key':'secret'}
        response=io.BytesIO(json.dumps({'content':[{'type':'text','text':'Привет!'}]}).encode())
        with patch.object(server.urllib.request,'urlopen',return_value=response) as mocked:
            result=server.send_chat_request(provider,'claude-sonnet-5',[
                {'role':'system','content':'Будь кратким.'},{'role':'user','content':'Привет'}
            ])
        request=mocked.call_args.args[0]
        body=json.loads(request.data.decode())
        self.assertEqual(request.full_url,'https://api.example.test/v1/messages')
        self.assertEqual(request.get_header('X-api-key'),'secret')
        self.assertEqual(request.get_header('Anthropic-version'),'2023-06-01')
        self.assertEqual(body['system'],'Будь кратким.')
        self.assertEqual(result['response'],'Привет!')

    def test_openai_compatible_request_uses_base_url_and_bearer_key(self):
        import io
        provider={'id':'fastypass','name':'FastBypass','kind':'cloud','format':'openai','base_url':'https://api.fastypass.com/v1','api_key':'secret'}
        response=io.BytesIO(json.dumps({'choices':[{'message':{'content':'Работает'}}]}).encode())
        with patch.object(server.urllib.request,'urlopen',return_value=response) as mocked:
            result=server.send_chat_request(provider,'claude-sonnet-5',[{'role':'user','content':'Тест'}])
        request=mocked.call_args.args[0]
        self.assertEqual(request.full_url,'https://api.fastypass.com/v1/chat/completions')
        self.assertEqual(request.get_header('Authorization'),'Bearer secret')
        self.assertEqual(result['response'],'Работает')

    def test_ollama_request_still_resolves_local_model(self):
        import io
        provider={'id':'ollama','name':'Ollama','kind':'local','format':'ollama','base_url':'http://127.0.0.1:11434'}
        response=io.BytesIO(json.dumps({'model':'qwen3:8b','message':{'content':'Локальный ответ'},'done':True}).encode())
        with patch.object(server,'resolve_ollama_model',return_value='qwen3:8b') as resolve, patch.object(server.urllib.request,'urlopen',return_value=response) as mocked:
            result=server.send_chat_request(provider,'qwen/qwen3-8b',[{'role':'user','content':'Тест'}])
        resolve.assert_called_once_with('qwen/qwen3-8b')
        request=mocked.call_args.args[0]
        self.assertEqual(request.full_url,'http://127.0.0.1:11434/api/chat')
        self.assertEqual(json.loads(request.data.decode())['model'],'qwen3:8b')
        self.assertEqual(result['response'],'Локальный ответ')

    def test_cloud_unauthorized_error_is_translated(self):
        exc=server.urllib.error.HTTPError('https://api.example.test/v1/chat/completions',401,'Unauthorized',{},None)
        with patch.object(server.urllib.request,'urlopen',side_effect=exc):
            with self.assertRaisesRegex(ValueError,'неверный API-ключ'):
                server.send_chat_request({'format':'openai','base_url':'https://api.example.test/v1','api_key':'bad'},'model-x',[{'role':'user','content':'Тест'}])

if __name__=='__main__': unittest.main()

