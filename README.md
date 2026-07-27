# RSS de DODF e DOU para o Portal RSR

Projeto independente que consulta fontes oficiais, filtra atos relevantes e publica RSS 2.0 para cadastro no módulo **Gerenciar Fontes** do Portal RSR.

## Escopo monitorado

1. Qualquer publicação do DODF relativa ao concurso vigente ou a futuros concursos da carreira Auditoria de Atividades Urbanas, incluindo Auditor Fiscal, Auditor, ATUB, editais, retificações, resultados, homologação, prorrogação, curso de formação, convocações, nomeações, desistências e reposicionamentos.
2. Publicação da LDO do exercício seguinte no DODF ou no DOU.
3. Alterações da LDO relacionadas a concursos, provimentos, nomeações, criação de cargos, anexos e despesas de pessoal.
4. Atos do DODF ou do DOU que autorizem novos concursos públicos.

## Arquitetura

```text
DODF: página diária oficial -> PDFs -> texto por página ----┐
                                                            ├-> regras -> histórico -> RSS 2.0
DOU: INLABS oficial -> ZIPs/XMLs de todas as matérias ------┘
```

A IA do Portal RSR continua responsável pela curadoria final e pela categoria exibida no painel. Este projeto usa filtros determinísticos antes disso, reduzindo ruído e custo.

## Publicação recomendada

Use um repositório **público** separado chamado `rss-diarios-oficiais`. O conteúdo coletado já é público, enquanto manter o produtor fora do `Portal_RSR` evita misturar dados operacionais com o código privado do site.

1. Crie no GitHub o repositório público `rocharafaelrsr/rss-diarios-oficiais`.
2. Envie todo o conteúdo desta pasta para a branch `main`.
3. Faça um cadastro gratuito no Portal INLABS da Imprensa Nacional.
4. Em **Settings > Secrets and variables > Actions**, crie os segredos `INLABS_EMAIL` e `INLABS_PASSWORD`.
5. Abra **Actions > Coletar DODF e DOU > Run workflow**.
6. Confira `docs/status.json` e os arquivos em `docs/feeds/`.
7. No Portal RSR, abra **Gerenciar Fontes** e importe `feeds.opml` para cadastrar apenas o feed geral. Para três fontes separadas, use `feeds-tematicos.opml`.

Não é necessário ativar GitHub Pages. `raw.githubusercontent.com` entrega o XML diretamente.

## URLs para cadastrar no Portal RSR

- Todos: `https://raw.githubusercontent.com/rocharafaelrsr/rss-diarios-oficiais/main/docs/feeds/todos.xml`
- ATUB: `https://raw.githubusercontent.com/rocharafaelrsr/rss-diarios-oficiais/main/docs/feeds/atub.xml`
- LDO: `https://raw.githubusercontent.com/rocharafaelrsr/rss-diarios-oficiais/main/docs/feeds/ldo.xml`
- Autorizações: `https://raw.githubusercontent.com/rocharafaelrsr/rss-diarios-oficiais/main/docs/feeds/autorizacoes-concursos.xml`

A opção recomendada é somente `todos.xml`, por exigir uma única leitura do seu motor. Use os três feeds temáticos apenas quando quiser controlar ativação e falhas separadamente. Não cadastre as duas modalidades ao mesmo tempo.

## Agenda

O workflow executa às 07h17, 11h17, 15h17 e 19h17 de Brasília. Os 17 minutos evitam a concentração de tarefas no minuto zero do GitHub Actions. A execução também pode ser disparada manualmente.

## Comportamento operacional

- Reconsulta os últimos 3 dias, protegendo contra edições tardias e atrasos de indexação.
- Retém itens por 730 dias.
- Deduplica por fonte, URL, página, regra e trecho.
- Processa todas as versões PDF listadas na página diária do DODF.
- Baixa do INLABS todos os ZIPs/XMLs do DOU listados para a data, incluindo edições adicionais disponibilizadas pelo portal.
- Interrompe com erro claro se as credenciais do INLABS não estiverem configuradas, evitando um monitor aparentemente saudável que ignore o DOU.
- Registra falhas parciais em `docs/status.json`.
- Se uma fonte falhar, preserva e publica resultados obtidos da outra.
- Se ambas falharem e nenhum documento for lido, o workflow termina com erro visível.

## Ajuste das regras

Edite `config/monitors.yml`. Os tipos aceitos são:

- `any_phrases`: pelo menos uma expressão deve ocorrer.
- `unconditional_phrases`: expressão inequívoca, aprova sem exigir `context_any`.
- `context_any`: exige contexto adicional.
- `all_groups`: exige pelo menos uma expressão de cada grupo.
- `any_regex`: expressão regular opcional.
- `exclude_phrases`: falso positivo conhecido.
- `max_span_chars`: distância máxima entre os grupos exigidos, para impedir que termos de atos diferentes na mesma página do DODF formem um falso positivo.

A regra `atividades urbanas` isolada é intencionalmente insuficiente, porque o termo aparece em matérias sem relação com a carreira. O nome do cargo também exige contexto de concurso, candidato, edital, convocação ou nomeação; assim, aposentadorias e atos funcionais comuns não entram no feed.

A publicação da LDO usa automaticamente o token `${NEXT_YEAR}`. Em 2026, por exemplo, procura a LDO de 2027; a regra avança sozinha nos anos seguintes.

## Execução local

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -q
python src/main.py --verbose
```

## Diagnóstico

O arquivo `docs/status.json` informa:

- início e fim da execução;
- datas consultadas;
- documentos examinados por fonte;
- correspondências novas;
- total armazenado;
- falhas sanitizadas.

O log completo fica na execução do GitHub Actions. Uma alteração estrutural em portal oficial aparecerá como ausência de links ou matérias, em vez de falhar silenciosamente.

## Limitações conhecidas

- Portais oficiais podem alterar HTML, parâmetros ou mecanismos antibot. Os seletores são tolerantes, mas não eternos.
- O PDF do DODF é examinado por página. Uma página com vários atos pode gerar um título genérico, embora o trecho e o link apontem para a página correta.
- O INLABS normalmente disponibiliza os arquivos depois da publicação oficial; a janela de 3 dias cobre atrasos e edições tardias.
- O XML do INLABS é adequado ao processamento, mas não substitui a versão oficial certificada. O link de cada item abre a busca oficial do DOU pelo título e pela data.

## Base técnica do DOU

O adaptador INLABS segue o fluxo público implementado pelo projeto governamental Ro-DOU: autenticação em `logar.php`, listagem diária em `index.php?p=AAAA-MM-DD` e download dos arquivos ZIP anunciados pelo portal. O código deste projeto é independente e reduzido ao necessário para gerar RSS.
