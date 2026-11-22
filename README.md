# RoboCop 2 no ROG Ally

Port Linux x86-64 do arcade **RoboCop 2** (Data East, 1991), versão **US v0.05** (`robocop2ua` no FBNeo/MAME). O programa Motorola 68000 da placa é traduzido para código x86-64 durante a compilação. O executável SDL2 e a biblioteca da placa são específicos deste jogo. A compilação usa as ROMs do próprio jogador.

## Imagem

- **16:9 sem esticar.** O raster da placa (320×240, pixels quadrados) foi ampliado para 428×240: 54 colunas reais de cenário, sprites e HUD de cada lado. A apresentação recorta menos de um pixel de cada lado da tela.
- **1080p.** A imagem é ampliada em escala inteira (5×) com vizinho mais próximo e reduzida em uma única passada linear até 1080 linhas.
- **60 fps.** A placa original roda a 57,8 Hz. Este port executa a lógica a 60,00 Hz, um quadro por atualização da tela do Ally; o jogo e a música ficam 3,8% mais rápidos que no arcade.

| Ação | ROG Ally | Teclado |
|---|---|---|
| Inserir crédito | View | 5 |
| Iniciar | Menu / Start | 1 ou Enter |
| Andar e mirar | Direcional ou analógico esquerdo | Setas |
| Botão 1 (tiro) | A | Z |
| Botão 2 | B | X |
| Botão 3 | X | C |
| Pausar ou continuar | Y | Esc |

O port guarda o estado da partida em `saves/progress.rc2`, a cada 30 segundos de jogo, ao pausar e no encerramento normal, e o carrega na próxima abertura. A gravação em disco roda fora do laço de vídeo.

## Compilar com suas ROMs

Em Linux x86-64, a compilação usa Git, Python 3, GCC/G++, Make, pkg-config e os arquivos de desenvolvimento do SDL2 e do zlib:

```sh
bash build.sh "/caminho/para/robocop2u.zip"
```

O script reconhece os 24 arquivos da versão US v0.05 pelo tamanho e CRC, com qualquer nome de arquivo, em set *merged* ou *split* e em ZIPs externos. Ele obtém a revisão fixada do FBNeo e gera o código nativo localmente. A saída fica em `.work/dist/`; execute `jogar.sh` ou adicione-o à Steam. `RC2_WORK` escolhe outra pasta de compilação e `RC2_MARGIN=0` gera a versão 4:3 original, sem nenhuma alteração no programa.

## Como funciona

O gerador monta a ROM de programa de 1 MB (quatro bancos de 256 KB). Para cada palavra par emite uma entrada x86-64 que carrega as palavras de extensão como imediato e salta para a semântica pré-compilada da instrução. O FBNeo guarda a memória do 68000 com os bytes trocados no host; os chips carregados no deslocamento +1 fornecem o byte alto de cada palavra.

O **HuC6280 de som não é traduzido**: ele roda no núcleo do FBNeo, assim como os chips de vídeo DECO16, a proteção DECO 146/104 e o som (YM2203, YM2151 e dois OKI M6295). A interface SDL2 apresenta a imagem e lê os controles.

## 16:9: adaptações no programa

Aplicadas somente ao código traduzido, conferidas byte a byte antes da troca (`aot/generate.py`). Rotinas novas ficam em `0x110000`, fora do espaço de ROM; só o código traduzido é executado ali.

- **Streaming do mapa.** As playfields 3 e 4 são anéis de 1024 pixels. A cada 16 pixels de rolagem o jogo copia uma coluna do mapa logo na borda da tela de 320 pixels (`0x010980`, `0x010ea2`). Cada chamada agora copia também as quatro colunas seguintes, calculadas como o jogo fará quando chegar lá; os contadores do jogo são restaurados em seguida.
- **Limites dos jogadores.** O X de tela (`0x1bb604`/`0x1bb606`) era limitado a [32, 288] por constantes lidas relativas ao PC (`0x1c33c`, `0x1c33e`). Leituras relativas ao PC vêm da memória da placa, então as comparações viraram imediatos do mesmo tamanho: [32 − m, 342], com m = min(54, câmera) e a câmera em `0x1bba04`. A mira (`0x023322`) vai de −22 a 342.
- **Pedidos de rolagem.** O jogo pede rolagem quando o X de tela passa de 160 ou fica abaixo de 112, comparando sem sinal; um X negativo, agora possível, era lido como "além de 160". As quatro comparações passaram a ter sinal.

- **Objetos que saem da tela.** Balas e outros objetos eram removidos a distâncias fixas da câmera (câmera − 16 e + 336 nas balas, `0x01da58`; câmera − 64 nos inimigos da lista `0x1b9xxx`, `0x01f6ac`; e `0x026d78`, `0x02a9be`, `0x02aa3c`, `0x02aa64`, `0x020e3a`). Cada distância cresceu 54 pixels e as comparações passaram a ter sinal.
- **Lista de sprites.** As rotinas em `0x06073a` (e quatro cópias) convertem o X do objeto para o X de 9 bits do sprite e escondiam tudo fora de [−32, 496], movendo para 496. Com o raster mais largo, a placa vira esse X em 428: [−84, −1] é a faixa direita e até 423 a esquerda; o próprio 496 cairia na faixa direita. A faixa aceita passou a [−84, 423] e o valor para esconder, 427, fica à esquerda da tela.

No adaptador (`board/rc2_board.cpp`):

- **Fim do mapa.** No fim de um trecho (por exemplo, a garagem da fase 1, câmera 1728) o jogo trava a rolagem, e a faixa direita ficaria além do fim do mapa: a playfield principal só tem blocos vazios e aparecem as camadas de trás (o fundo cinza e a faixa azul com uma diagonal branca). O mapa de prioridade do DECO16 identifica a camada de cada pixel. Uma coluna das faixas extras em que a camada principal (a da frente nas 320 colunas centrais) cobre menos de 10% das linhas está fora do mapa. Nessa coluna, os pixels de cenário ficam pretos; sprites e HUD continuam visíveis. A regra não é aplicada quando alguma coluna central também não tem a camada principal.
- **Início do trecho.** À esquerda do início de cada trecho do mapa (o menor X de câmera desde o último salto), a cor de fundo dominante vira preta, mantendo os personagens. Uma lateral com 97% de uma só cor também fica preta.

## Verificação

- **Tradução do 68000.** Com a margem 0, a versão traduzida e o interpretador Musashi executaram as mesmas 14.334.794 instruções (PC, SR e os 16 registradores) nos primeiros 900 quadros. Em 6.000 quadros com crédito, início, tiros, pulo e avanço, vídeo e áudio coincidiram.
- **16:9.** No mesmo quadro, as 320 colunas centrais coincidem pixel a pixel com a imagem 4:3. Com as cópias adiantadas, a faixa direita mostra o mapa ao rolar (antes, só a cor de fundo).
- **Limites.** Partindo do mesmo estado, o jogador para em X = −22 à esquerda (32 pixels da borda larga) e a câmera não se move; na versão original ele parava em 32.
- **No ROG Ally.** O atalho da Steam abriu o executável em 1920×1080; a apresentação ficou em 60,00 fps (no máximo dois quadros atrasados a cada 600, pior intervalo de 39 ms).

- **Fim do trecho.** Partindo do save do jogador na garagem, a faixa direita fica preta e a explosão e o veículo continuam inteiros. Em 24.000 quadros de partida automática, a faixa direita continuou mostrando o mapa durante a rolagem.
- **Balas e personagens nas faixas.** As balas chegam às duas faixas extras; inimigos e veículos aparecem inteiros até a borda física da tela em 40.000 quadros de partida automática.

Ainda não verificado: as fases 2 em diante e o modo para dois jogadores. Limites conhecidos: no fim de um trecho, se o bloco seguinte do mapa não estiver vazio, a faixa direita ainda pode mostrar cenário de outro trecho; inimigos que o jogo cria logo depois da borda direita original podem surgir já dentro da faixa direita.
