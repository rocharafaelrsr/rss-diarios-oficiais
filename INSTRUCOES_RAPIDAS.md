# Instalação rápida

1. Crie um repositório **público** no GitHub com o nome `rss-diarios-oficiais`.
2. Envie todo o conteúdo desta pasta para a branch `main`.
3. Cadastre-se no INLABS e adicione ao repositório os Actions Secrets `INLABS_EMAIL` e `INLABS_PASSWORD`.
4. Antes de mesclar alterações, confirme que o workflow **Validar coletor** ficou verde.
5. Execute manualmente o workflow **Coletar DODF** e confirme que ficou verde.
6. Execute manualmente o workflow **Coletar DOU** e confirme que ficou verde.
7. No Portal RSR, em **Gerenciar Fontes**, importe `feeds.opml` para usar o feed geral recomendado. Para separar as fontes por tema, importe `feeds-tematicos.opml` no lugar dele.

Não use os dois OPMLs ao mesmo tempo, porque isso repetiria a coleta dos mesmos atos.
