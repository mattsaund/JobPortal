"""Every AI JobPortal can run on, as data. ai/providers.py holds the logic around this table.

A provider needs only an entry here when it speaks one of the three request formats in ai/client.py ("wire"): OpenAI's
Responses API, the chat completions API most services share, or Anthropic's Messages API. Keys of an entry:
- name: what the Connect popup shows. aliases: other words the popup's search finds it by.
- wire: "responses", "chat" or "anthropic". base: the API's address. With "fields", it holds their ids, as in {region}.
- auth: "chatgpt" (Sign in with ChatGPT) or "key". signin: it also offers a browser sign-in that makes the key.
- fields: address parts the user fills in. A field with the id "url" is the whole address.
- needs_key: False for a service that works without one. local: it runs on this computer. custom: any other service.
- key_url: where the user gets a key. key_prefix: how its keys start, as a hint.
- models: the model list's path when it isn't /models. models_url: its full address when it's outside the base.
- search: can search the web itself. effort: how it takes the reasoning effort ("reasoning" object or "reasoning_effort").
- tool_name: tool replies must name their tool. max_tokens: sent on every request, for a service with a low default.
- body and headers: extra request fields, for a service that needs them. free: it has an ongoing free tier.
- note: one short line, only when leaving it out could cost the user something.

A provider whose /models address doesn't exist still connects: the Connect popup then asks for a model name."""


def _api(name: str, base: str, key_url: str = "", **more) -> dict:
    """An API-key provider on the chat completions wire, the shape most of them have."""
    return {"name": name, "wire": "chat", "base": base, "auth": "key", "key_url": key_url, **more}


def _local(name: str, url: str, note: str = "") -> dict:
    """A model server on this computer. It speaks the chat completions API and needs no key."""
    return {"name": name, "wire": "chat", "base": "", "auth": "key", "local": True, "needs_key": False, "note": note,
            "fields": [{"id": "url", "label": "Address", "default": url}]}


PROVIDERS = {
    # ---- the largest ones, and the ones with a browser sign-in
    "chatgpt": {"name": "ChatGPT", "wire": "responses", "base": "https://api.openai.com/v1", "auth": "chatgpt", "search": True,
                "aliases": "openai gpt", "note": "Needs a Go, Plus or Pro plan."},
    "openrouter": _api("OpenRouter", "https://openrouter.ai/api/v1", "https://openrouter.ai/settings/keys", signin=True, free=True,
                       models="/models/user", effort="reasoning", key_prefix="sk-or-"),
    "pollinations": _api("Pollinations", "https://gen.pollinations.ai/v1", "https://enter.pollinations.ai/keys", signin=True, key_prefix="sk_"),
    "openai": {"name": "OpenAI API", "wire": "responses", "base": "https://api.openai.com/v1", "auth": "key", "search": True,
               "key_prefix": "sk-", "key_url": "https://platform.openai.com/api-keys", "aliases": "gpt"},
    "anthropic": {"name": "Claude", "wire": "anthropic", "base": "https://api.anthropic.com/v1", "auth": "key", "search": True,
                  "key_prefix": "sk-ant-", "key_url": "https://platform.claude.com/settings/keys", "aliases": "anthropic sonnet opus haiku"},
    "gemini": _api("Gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "https://aistudio.google.com/apikey", free=True,
                   effort="reasoning_effort", key_prefix="AIza", aliases="google", note="Free tier: Google may review what you send."),
    "xai": _api("Grok", "https://api.x.ai/v1", "https://console.x.ai", key_prefix="xai-", aliases="xai"),
    "mistral": _api("Mistral", "https://api.mistral.ai/v1", "https://console.mistral.ai/api-keys", tool_name=True, aliases="le chat"),
    "deepseek": _api("DeepSeek", "https://api.deepseek.com", "https://platform.deepseek.com/api_keys", key_prefix="sk-"),
    "groq": _api("Groq", "https://api.groq.com/openai/v1", "https://console.groq.com/keys", free=True, key_prefix="gsk_"),
    "perplexity": {"name": "Perplexity", "wire": "responses", "base": "https://api.perplexity.ai/v1", "auth": "key", "search": True,
                   "key_url": "https://console.perplexity.ai/project/keys", "aliases": "sonar"},
    # ---- model makers
    "cohere": _api("Cohere", "https://api.cohere.ai/compatibility/v1",
                  "https://dashboard.cohere.com/api-keys", models_url="https://api.cohere.com/v1/models", free=True, aliases="command"),
    "ai21": _api("AI21", "https://api.ai21.com/studio/v1", "https://docs.ai21.com/docs/create-api-key.md", max_tokens=4096, aliases="jamba"),
    "reka": _api("Reka", "https://api.reka.ai/v1", "https://developer.reka.ai/keys"),
    "upstage": _api("Upstage", "https://api.upstage.ai/v1", "https://console.upstage.ai/api-keys", aliases="solar"),
    "liquid": _api("Liquid AI", "https://api.liquid.ai/openai/v1", "https://console.liquid.ai/dashboard/api-keys", key_prefix="liquid_"),
    "sakana": _api("Sakana AI", "https://api.sakana.ai/v1", "https://console.sakana.ai/api-keys", key_prefix="fish_"),
    "reflection": _api("Reflection AI", "https://api.reflection.ai/openai/v1", "https://platform.reflection.ai"),
    "poolside": _api("Poolside", "https://inference.poolside.ai/v1", "https://platform.poolside.ai/"),
    "arcee": _api("Arcee AI", "https://api.arcee.ai/api/v1", "https://platform.arcee.ai/api/api-keys"),
    "meta": _api("Meta AI", "https://api.meta.ai/v1", "https://dev.meta.ai", aliases="llama"),
    "qwen": _api("Qwen (Alibaba)", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
                  "https://modelstudio.console.alibabacloud.com/cn-beijing/settings/api-key", aliases="dashscope alibaba tongyi"),
    "zai": _api("GLM (Z.ai)", "https://api.z.ai/api/paas/v4", "https://z.ai/manage-apikey/apikey-list", aliases="zhipu chatglm"),
    "moonshot": _api("Kimi (Moonshot)", "https://api.moonshot.ai/v1", "https://platform.kimi.ai/console/api-keys", tool_name=True, aliases="kimi"),
    "minimax": _api("MiniMax", "https://api.minimax.io/v1", "https://platform.minimax.io/console/plan", key_prefix="sk-"),
    "qianfan": _api("ERNIE (Baidu Qianfan)", "https://qianfan.baidubce.com/v2",
                  "https://console.bce.baidu.com/qianfan/", key_prefix="bce-v3/ALTAK-", aliases="wenxin baidu"),
    "tencent": _api("Hunyuan (Tencent)", "https://tokenhub-intl.tencentcloudmaas.com/v1",
                  "https://console.cloud.tencent.com/tokenhub/apikey", aliases="hunyuan tokenhub"),
    "volcengine": _api("Doubao (Volcengine Ark)", "https://ark.cn-beijing.volces.com/api/v3",
                  "https://ark.volcengine.com/region:cn-beijing/apikey", aliases="bytedance ark doubao"),
    "byteplus": _api("BytePlus ModelArk", "https://ark.ap-southeast.bytepluses.com/api/v3", "https://console.byteplus.com/ark", aliases="bytedance"),
    "baichuan": _api("Baichuan", "https://api.baichuan-ai.com/v1", "https://platform.baichuan-ai.com"),
    "spark": _api("Spark (iFlytek)", "https://spark-api-open.xf-yun.com/v1",
                  "https://console.xfyun.cn/services/cbm", body={'tool_calls_switch': True}, free=True, aliases="xunfei"),
    "sensenova": _api("SenseNova (SenseTime)", "https://token.sensenova.cn/v1", "https://platform.sensenova.cn", key_prefix="sk-", free=True),
    "stepfun": _api("StepFun", "https://api.stepfun.ai/v1", "https://platform.stepfun.ai"),
    "xiaomi": _api("MiMo (Xiaomi)", "https://api.xiaomimimo.com/v1",
                  "https://platform.xiaomimimo.com/#/console/api-keys", key_prefix="sk-", aliases="mimo"),
    "longcat": _api("LongCat (Meituan)", "https://api.longcat.chat/openai/v1", "https://longcat.chat/platform/api_keys"),
    "bailing": _api("Ling (Ant Group)", "https://api.ant-ling.com/v1", "https://chat.ant-ling.com/open", free=True, aliases="ant"),
    "clova": _api("CLOVA (Naver)", "https://clovastudio.stream.ntruss.com/v1/openai",
                  "https://clovastudio.ncloud.com", max_tokens=4096, key_prefix="nv-", aliases="naver hyperclova"),
    "sarvam": _api("Sarvam", "https://api.sarvam.ai/v2", "https://dashboard.sarvam.ai", max_tokens=8192),
    "nous": _api("Nous Portal", "https://inference-api.nousresearch.com/v1", "https://portal.nousresearch.com"),
    # ---- clouds
    "azure": _api("Azure OpenAI", "https://{resource}.openai.azure.com/openai/v1",
                  "https://ai.azure.com", fields=[{'id': 'resource', 'label': 'Resource name', 'placeholder': 'my-resource'}], aliases="microsoft foundry openai"),
    "bedrock": _api("Amazon Bedrock", "https://bedrock-mantle.{region}.api.aws/v1",
                  "https://console.aws.amazon.com/bedrock", fields=[{'id': 'region', 'label': 'Region', 'default': 'us-east-1'}], aliases="aws amazon"),
    "cloudflare": _api("Cloudflare Workers AI", "https://api.cloudflare.com/client/v4/accounts/{account}/ai/v1",
                  "https://developers.cloudflare.com/fundamentals/api/get-started/create-token/", fields=[{'id': 'account', 'label': 'Account ID'}], free=True, aliases="workers"),
    "oci": _api("Oracle Cloud AI", "https://inference.generativeai.{region}.oci.oraclecloud.com/openai/v1",
                  "https://docs.oracle.com/en-us/iaas/Content/generative-ai/create-api-key.htm", fields=[{'id': 'region', 'label': 'Region', 'default': 'us-chicago-1'}, {'id': 'project', 'label': 'Project OCID'}], aliases="oracle", headers={'OpenAI-Project': '{project}'}),
    "databricks": _api("Databricks", "https://{workspace}/ai-gateway/mlflow/v1",
                  "", fields=[{'id': 'workspace', 'label': 'Workspace host', 'placeholder': 'example.cloud.databricks.com'}]),
    "snowflake": _api("Snowflake Cortex", "https://{account}.snowflakecomputing.com/api/v2/cortex/v1",
                  "https://docs.snowflake.com/en/user-guide/programmatic-access-tokens#label-pat-generate", fields=[{'id': 'account', 'label': 'Account identifier'}]),
    "huawei": _api("Huawei ModelArts", "https://api-ap-southeast-1.modelarts-maas.com/openai/v1",
                  "https://console-intl.huaweicloud.com/maas/?#/model-studio/authmanage"),
    "nvidia": _api("NVIDIA NIM", "https://integrate.api.nvidia.com/v1", "https://build.nvidia.com/settings", free=True, aliases="nim"),
    "digitalocean": _api("DigitalOcean", "https://inference.do-ai.run/v1",
                  "https://cloud.digitalocean.com/model-studio/manage-keys", key_prefix="doo-v1-"),
    "vultr": _api("Vultr", "https://api.vultrinference.com/v1", "https://my.vultr.com"),
    "scaleway": _api("Scaleway", "https://api.scaleway.ai/v1", "https://console.scaleway.com/iam/api-keys"),
    "ovhcloud": _api("OVHcloud", "https://oai.endpoints.kepler.ai.cloud.ovh.net/v1", "https://www.ovh.com/manager", needs_key=False, free=True),
    "ionos": _api("IONOS", "https://openai.inference.de-txl.ionos.com/v1",
                  "https://docs.ionos.com/cloud/set-up-ionos-cloud/management/identity-access-management/token-manager.md"),
    "stackit": _api("STACKIT", "https://api.openai-compat.model-serving.eu01.onstackit.cloud/v1", "https://portal.stackit.cloud"),
    "evroc": _api("evroc", "https://models.think.evroc.com/v1", "https://evroc.com"),
    "cloudferro": _api("CloudFerro Sherlock", "https://api-sherlock.cloudferro.com/openai/v1", "https://sherlock.cloudferro.com"),
    "berget": _api("Berget AI", "https://api.berget.ai/v1", "https://console.berget.ai"),
    "regolo": _api("Regolo", "https://api.regolo.ai/v1", "https://dashboard.regolo.ai/"),
    "nscale": _api("Nscale", "https://inference.api.nscale.com/v1", "https://console.nscale.com"),
    "crusoe": _api("Crusoe", "https://api.inference.crusoecloud.com/v1", "https://console.crusoecloud.com/foundry/models"),
    "gmi": _api("GMI Cloud", "https://api.gmi-serving.com/v1", "https://console.gmicloud.ai"),
    # ---- model hosts
    "together": _api("Together AI", "https://api.together.ai/v1", "https://api.together.ai/settings/projects/~current/api-keys"),
    "fireworks": _api("Fireworks AI", "https://api.fireworks.ai/inference/v1", "https://app.fireworks.ai/settings/users/api-keys", key_prefix="fw_"),
    "cerebras": _api("Cerebras", "https://api.cerebras.ai/v1", "https://cloud.cerebras.ai", key_prefix="csk-"),
    "sambanova": _api("SambaNova", "https://api.sambanova.ai/v1", "https://cloud.sambanova.ai/dashboard", free=True),
    "deepinfra": _api("DeepInfra", "https://api.deepinfra.com/v1/openai", "https://deepinfra.com/dash/keys"),
    "nebius": _api("Nebius", "https://api.tokenfactory.nebius.com/v1", "https://tokenfactory.nebius.com/project/api-keys"),
    "novita": _api("Novita AI", "https://api.novita.ai/openai", "https://novita.ai/settings/key-management", key_prefix="sk_"),
    "hyperbolic": _api("Hyperbolic", "https://api.hyperbolic.ai/inference/v1", "https://app.hyperbolic.ai/settings/api-keys", key_prefix="sk_live_"),
    "featherless": _api("Featherless", "https://api.featherless.ai/v1", "https://featherless.ai"),
    "chutes": _api("Chutes", "https://llm.chutes.ai/v1", "https://chutes.ai", key_prefix="cpk_"),
    "parasail": _api("Parasail", "https://api.parasail.io/v1", "https://www.saas.parasail.io/keys"),
    "siliconflow": _api("SiliconFlow", "https://api.siliconflow.com/v1", "https://cloud.siliconflow.com/account/ak", key_prefix="sk-"),
    "infini": _api("Infini-AI", "https://cloud.infini-ai.com/maas/v1", "https://cloud.infini-ai.com/iam/secret/key", key_prefix="sk-"),
    "baseten": _api("Baseten", "https://inference.baseten.co/v1", "https://app.baseten.co/settings/api_keys", key_prefix="b10_"),
    "friendli": _api("FriendliAI", "https://api.friendli.ai/serverless/v1", "https://friendli.ai/suite", key_prefix="flp_"),
    "wandb": _api("W&B Inference", "https://api.inference.wandb.ai/v1", "https://forge.coreweave.com/settings", aliases="weights biases coreweave"),
    "huggingface": _api("Hugging Face", "https://router.huggingface.co/v1",
                  "https://huggingface.co/settings/tokens/new?ownUserPermissions=inference.serverless.write&tokenType=fineGrained", key_prefix="hf_", aliases="hf"),
    "modelscope": _api("ModelScope", "https://api-inference.modelscope.cn/v1", "https://modelscope.cn/my/myaccesstoken", free=True),
    "qiniu": _api("Qiniu", "https://api.qnaigc.com/v1", "https://portal.qiniu.com"),
    "cortecs": _api("Cortecs", "https://api.cortecs.ai/v1", "https://docs.cortecs.ai/web-console/api-keys.md"),
    "synthetic": _api("Synthetic", "https://api.synthetic.new/openai/v1", "https://dev.synthetic.new/docs/api/overview"),
    "ionet": _api("io.net", "https://api.intelligence.io.solutions/api/v1", "https://ai.io.net/ai/api-keys", free=True),
    "akashml": _api("AkashML", "https://api.akashml.com/v1", "https://akashml.com/login", key_prefix="akml-"),
    "inferencenet": _api("Inference.net", "https://api.inference.net/v1", "https://inference.net"),
    "tinfoil": _api("Tinfoil", "https://inference.tinfoil.sh/v1", "https://tinfoil.sh"),
    "phala": _api("Phala", "https://inference.phala.com/v1", "https://cloud.phala.network"),
    "nearai": _api("NEAR AI", "https://cloud-api.near.ai/v1", "https://cloud.near.ai"),
    "arliai": _api("Arli AI", "https://api.arliai.com/v1", "https://www.arliai.com/account"),
    "infermatic": _api("Infermatic", "https://api.totalgpt.ai/v1", "https://ui.infermatic.ai"),
    "mancer": _api("Mancer", "https://neuro.mancer.tech/oai/v1", "https://mancer.tech", free=True),
    "venice": _api("Venice", "https://api.venice.ai/api/v1", "https://venice.ai/settings/api"),
    "ollama-cloud": _api("Ollama Cloud", "https://ollama.com/v1", "https://ollama.com/settings/keys"),
    # ---- gateways
    "vercel": _api("Vercel AI Gateway", "https://ai-gateway.vercel.sh/v1",
                  "https://vercel.com/d?to=%2F%5Bteam%5D%2F%7E%2Fai-gateway%2Fapi-keys&title=AI+Gateway+API+Keys", key_prefix="vck_"),
    "poe": _api("Poe", "https://api.poe.com/v1", "https://poe.com/api/keys"),
    "requesty": _api("Requesty", "https://router.requesty.ai/v1", "https://app.requesty.ai/api-keys", free=True, note="Resells other AI models."),
    "kilo": _api("Kilo Gateway", "https://ai-gateway.kilo.ai/api/v1", "https://app.kilo.ai", free=True, note="Resells other AI models."),
    "glama": _api("Glama", "https://glama.ai/api/gateway/openai/v1", "https://glama.ai"),
    "zenmux": _api("ZenMux", "https://zenmux.ai/api/v1", "https://zenmux.ai/platform/pay-as-you-go", note="Resells other AI models."),
    "nanogpt": _api("NanoGPT", "https://api.nano-gpt.com/api/v1", "https://nano-gpt.com/api", note="Resells other AI models."),
    "fastrouter": _api("FastRouter", "https://api.fastrouter.ai/api/v1",
                  "https://fastrouter.ai", key_prefix="sk-v1-", note="Resells other AI models."),
    "aihubmix": _api("AIHubMix", "https://aihubmix.com/v1",
                  "https://console.aihubmix.com/workspaces/default/keys", key_prefix="sk-", free=True, note="Resells other AI models."),
    "aimlapi": _api("AI/ML API", "https://api.aimlapi.com/v1", "https://aimlapi.com/app/keys", note="Resells other AI models."),
    "edenai": _api("Eden AI", "https://api.edenai.run/v3", "https://app.edenai.run/", note="Resells other AI models."),
    "abacus": _api("Abacus.AI", "https://routellm.abacus.ai/v1",
                  "https://abacus.ai/app/route-llm-apis", aliases="routellm", note="Resells other AI models."),
    "atlascloud": _api("Atlas Cloud", "https://api.atlascloud.ai/v1",
                  "https://www.atlascloud.ai/console/api-keys", key_prefix="apikey-", note="Resells other AI models."),
    "cometapi": _api("CometAPI", "https://api.cometapi.com/v1",
                  "https://www.cometapi.com/console/token", models_url="https://api.cometapi.com/api/models", note="Resells other AI models."),
    "ai302": _api("302.AI", "https://api.302.ai/v1", "https://302.ai", models="/models?llm=1", note="Resells other AI models."),
    # ---- on this computer
    "ollama": _local("Ollama", "http://localhost:11434/v1", "Set OLLAMA_CONTEXT_LENGTH to 16000 or more."),
    "lmstudio": _local("LM Studio", "http://localhost:1234/v1"),
    "llamacpp": _local("llama.cpp", "http://127.0.0.1:9931/v1"),
    "vllm": _local("vLLM", "http://localhost:8000/v1"),
    "localai": _local("LocalAI", "http://localhost:8080/v1"),
    "jan": _local("Jan", "http://127.0.0.1:1337/v1"),
    "koboldcpp": _local("KoboldCpp", "http://localhost:5001/v1"),
    "textgen": _local("text-generation-webui", "http://127.0.0.1:5000/v1"),
    "gpt4all": _local("GPT4All", "http://localhost:4891/v1"),
    "mlxlm": _local("MLX", "http://127.0.0.1:8080/v1"),
    "dmr": _local("Docker Model Runner", "http://localhost:12434/engines/v1"),
    "lemonade": _local("Lemonade", "http://localhost:13305/v1"),
    "sglang": _local("SGLang", "http://127.0.0.1:30000/v1"),
    "litellm": _local("LiteLLM proxy", "http://localhost:4000/v1"),
    # ---- anything else with an OpenAI-compatible API
    "custom": {"name": "Custom (OpenAI-compatible)", "wire": "chat", "base": "", "auth": "key", "custom": True, "needs_key": False,
               "fields": [{"id": "url", "label": "API address", "placeholder": "https://example.com/v1"}]},
}
