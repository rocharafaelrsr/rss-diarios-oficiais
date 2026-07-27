# Validação técnica

Validações executadas antes da entrega:

- compilação de todos os módulos Python;
- testes das regras de ATUB, LDO e autorização;
- teste de proximidade contra falsos positivos na mesma página;
- teste do token dinâmico de ano seguinte;
- teste de deduplicação e retenção;
- teste de geração e leitura de RSS 2.0;
- teste de parsing de XML do INLABS;
- teste de aceitação apenas de PDFs no domínio oficial do DODF.

A validação ponta a ponta contra os portais ao vivo depende de acesso externo e de credenciais válidas do INLABS. O workflow registra ausência de documentos, falhas de autenticação e mudanças estruturais em `docs/status.json` e no log do GitHub Actions.
