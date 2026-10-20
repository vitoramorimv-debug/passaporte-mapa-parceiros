# Mapa Interativo de Parceiros — Passaporte Gastronômico Marília

Protótipo de mapa web (Leaflet + OpenStreetMap) com os parceiros do Passaporte.
A pessoa informa o endereço ou usa o GPS e vê a lista dos parceiros mais próximos,
com detalhes da oferta e botões para Google Maps, Waze e Instagram.

## Estrutura

- `index.html` — a página do mapa (sem build, abre direto no navegador).
- `data/parceiros_raw.json` — exportação do CRM de Parceiros (Notion, base "New form").
- `scripts/geocode.py` — converte endereços em coordenadas (ViaCEP + Google Geocoding + Nominatim/Photon)
  e gera `data/parceiros.json` e `data/parceiros.js` (este último é o que a página carrega).
- `data/geocode_cache.json` — cache das consultas; apague para refazer tudo.
- `.env` (não versionar) — chave da Google Geocoding API: `GOOGLE_MAPS_API_KEY=...`.
- `data/overrides.json` (opcional) — correções manuais de posição:
  `{"<id do parceiro>": {"lat": -22.21, "lon": -49.94, "endereco": "rótulo opcional", "obs": "..."}}`.

## Rodar localmente

```bash
python3 -m http.server 8765
```

e abra http://localhost:8765. O GPS só funciona em `localhost` ou HTTPS.

## Chave da Google Geocoding API

O OpenStreetMap quase não tem numeração de imóveis em Marília, então o script usa a Google
Geocoding API para posicionar cada parceiro no número certo (`precisao = "endereco"`).
Sem a chave o script ainda roda, mas a maioria dos parceiros fica no meio da rua (`precisao = "rua"`).

1. No [Google Cloud Console](https://console.cloud.google.com/), crie (ou use) um projeto, habilite a
   **Geocoding API** e crie uma chave de API (restrinja a chave a essa API).
2. Salve a chave em um arquivo `.env` na raiz do projeto:
   ```
   GOOGLE_MAPS_API_KEY=sua-chave-aqui
   ```
   ou exporte a variável antes de rodar: `export GOOGLE_MAPS_API_KEY=sua-chave-aqui`.
3. Não compartilhe nem versione o `.env`.

Como funciona: para cada parceiro com número, o script consulta
`"{logradouro}, {numero}, {bairro}, Marília, SP, Brasil"` e só aceita resultados com
`location_type` ROOFTOP ou RANGE_INTERPOLATED dentro de Marília. Sem resultado aceitável, cai para o
Nominatim/Photon (rua → bairro → cidade). As consultas ficam no `data/geocode_cache.json`
(erros da API não são cacheados), e `data/overrides.json` continua tendo prioridade.

## Atualizar os parceiros

1. Exporte do Notion para `data/parceiros_raw.json` (só entram no mapa os com status "Página Aprovada").
2. Rode `python3 scripts/geocode.py | tee data/geocode_log.txt` (com a chave configurada, veja acima).
3. O fim do log traz o resumo por precisão e a lista dos parceiros com posição aproximada
   (`precisao` diferente de `endereco`/`manual`). Confira esses no mapa e, se precisar, ajuste em
   `data/overrides.json` e rode o script de novo.

## Publicação

O mapa público está no Lovable: https://mapa-passaporte-marilia.lovable.app
(projeto "Mapa de Sabores de Marília", editor em https://lovable.dev/projects/e676f9aa-5aa7-464e-be3d-aefffad6e0fe).

A página do Lovable não guarda os dados: ela lê em tempo real o arquivo
`data/parceiros.json` deste repositório no GitHub
(https://raw.githubusercontent.com/vitoramorimv-debug/passaporte-mapa-parceiros/main/data/parceiros.json).
Para atualizar os parceiros no mapa publicado basta rodar o `scripts/geocode.py`, conferir
localmente e fazer `git push`; não gasta crédito do Lovable.

O `index.html` deste repositório é o protótipo original em HTML puro e continua funcionando
localmente (`python3 -m http.server 8765`). A chave do Google fica no `.env`, que está no
`.gitignore` e nunca sobe.
