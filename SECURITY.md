# Segurança

O DODF é acessado sem credenciais. O DOU usa uma conta do Portal INLABS.

As credenciais devem existir somente em **GitHub Actions Secrets**, com os nomes `INLABS_EMAIL` e `INLABS_PASSWORD`. O workflow injeta os valores apenas durante a execução. Não grave senhas, cookies, arquivos `.env` ou ZIPs baixados no Git.

O coletor persiste apenas metadados e trechos de atos públicos. Cookies de sessão do INLABS permanecem em memória e são descartados ao término do job.
