# RSS de DODF e DOU para o Portal RSR

Projeto independente que consulta fontes oficiais, filtra atos relevantes e publica RSS 2.0 para cadastro no módulo **Gerenciar Fontes** do Portal RSR.

## Escopo monitorado

1. Qualquer publicação do DODF relativa ao concurso vigente ou a futuros concursos da carreira Auditoria de Atividades Urbanas, incluindo Auditor Fiscal, Auditor, ATUB, editais, retificações, resultados, homologação, prorrogação, curso de formação, convocações, nomeações, desistências e reposicionamentos.
2. Publicação da LDO do exercício seguinte no DODF ou no DOU.
3. Alterações da LDO relacionadas a concursos, provimentos, nomeações, criação de cargos, anexos e despesas de pessoal.
4. Atos do DODF ou do DOU que autorizem novos concursos públicos.

## Arquitetura

```text
DODF: portal oficial -> PDFs ─┐
            fallback SINJ-DF ─┤
                              ├-> regras estritas -> histórico -> RSS 2.0
DOU: INLABS -> ZIPs/XMLs ─────┤
      fallback busca pública ─┘
```

A IA do Portal RSR continua responsável pela curadoria final e pela categoria exibida no painel. Este projeto usa filtros determinísticos antes disso, reduzindo ruído e custo.

## Publicação recomendada

Use um repositório **público** separado chamado `rss-diarios-oficiais`. O conteúdo coletado já é público, enquanto manter o produtor fora do `Portal_RSR` evita misturar dados operacionais com o código privado do site.

1. Crie no GitHub o repositório público `rocharafaelrsr/rss-diarios-oficiais`.
2. Envie todo o conteúdo desta pasta para a branch `main`.
3. Faça um cadastro gratuito no Portal INLABS da Imprensa Nacional.
4. Em **Settings > Secrets and variables > Actions**, crie os segredos `INLABS_EMAIL` e `INLABS_PASSWORD`.
5. Abra **Actions > Coletar DODF > Run workflow** e confirme a execução.
6. Abra **Actions > Coletar DOU > Run workflow** e confirme a execução.
7. Confira `docs/status-dodf.json`, `docs/status-dou.json` e os arquivos em `docs/feeds/`.
8. No Portal RSR, abra **Gerenciar Fontes** e importe `feeds.opml` para cadastrar apenas o feed geral. Para três fontes separadas, use `feeds-tematicos.opml`.

Não é necessário ativar GitHub Pages. `raw.githubusercontent.com` entrega o XML diretamente.

## URLs para cadastrar no Portal RSR

- Todos: `https://raw.githubusercontent.com/rocharafaelrsr/rss-diarios-oficiais/main/docs/feeds/todos.xml`
- ATUB: `https://raw.githubusercontent.com/rocharafaelrsr/rss-diarios-oficiais/main/docs/feeds/atub.xml`
- LDO: `https://raw.githubusercontent.com/rocharafaelrsr/rss-diarios-oficiais/main/docs/feeds/ldo.xml`
- Autorizações: `https://raw.githubusercontent.com/rocharafaelrsr/rss-diarios-oficiais/main/docs/feeds/autorizacoes-concursos.xml`

A opção recomendada é somente `todos.xml`, por exigir uma única leitura do seu motor. Use os três feeds temáticos apenas quando quiser controlar ativação e falhas separadamente. Não cadastre as duas modalidades ao mesmo tempo.

## Agenda

Os workflows são independentes, mas compartilham um grupo de concorrência para nunca executar ou publicar simultaneamente:

- **Coletar DODF:** 07h17, 11h17, 15h17 e 19h17 de Brasília.
- **Coletar DOU:** 07h27, 11h27, 15h27 e 19h27 de Brasília.

Ambos também podem ser disparados manualmente.

## Comportamento operacional

- Reconsulta os últimos 5 dias, protegendo contra edições tardias, fins de semana e atrasos de indexação.
- Retém itens por 730 dias.
- Mantém identidade específica por ato e uma chave de recolhimento para substituir itens legados sem duplicação.
- Processa todas as versões PDF listadas na página diária do DODF.
- Usa o SINJ-DF como fallback oficial quando o portal diário do DODF estiver indisponível.
- Baixa do INLABS todos os ZIPs/XMLs do DOU listados para a data, incluindo edições adicionais disponibilizadas pelo portal.
- Usa a busca pública oficial e seu JSON estruturado como fallback do DOU, com contingência HTML paginada.
- Os workflows de DODF e DOU são autônomos; falha de uma fonte não bloqueia a outra.
- Se a `main` avançar durante a coleta, o workflow refaz somente sua fonte sobre o estado novo e tenta publicar novamente.

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

Os arquivos `docs/status-dodf.json` e `docs/status-dou.json` informam:

- início e fim da execução;
- data de referência;
- documentos examinados;
- backend utilizado;
- correspondências novas;
- total armazenado;
- falhas sanitizadas.

O log completo fica na execução do GitHub Actions. Uma alteração estrutural em portal oficial aparecerá como ausência de links ou matérias, em vez de falhar silenciosamente.

## Limitações conhecidas

- Portais oficiais podem alterar HTML, parâmetros ou mecanismos antibot. Os seletores são tolerantes, mas não eternos.
- O PDF do DODF é examinado por página; o coletor recorta o ato correspondente pelos termos encontrados, mas diagramações excepcionalmente irregulares podem exigir ajuste.
- O INLABS normalmente disponibiliza os arquivos depois da publicação oficial; a janela de 5 dias cobre atrasos e edições tardias.
- O XML do INLABS e a busca pública são adequados ao monitoramento, mas não substituem a versão oficial certificada.

## Base técnica do DOU

O adaptador INLABS segue o fluxo público implementado pelo projeto governamental Ro-DOU: autenticação em `logar.php`, listagem diária em `index.php?p=AAAA-MM-DD` e download dos arquivos ZIP anunciados pelo portal. O fallback consulta o buscador oficial, lê seu JSON estruturado e, em mudança de esquema, percorre os resultados HTML. O código deste projeto é independente e reduzido ao necessário para gerar RSS.
