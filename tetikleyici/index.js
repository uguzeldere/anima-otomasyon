// GitHub cron'u saatlerce gecikiyor veya atliyor. Bu Worker saatinde workflow_dispatch cagirir.
const REPO = 'uguzeldere/anima-otomasyon';

// wrangler.jsonc icindeki crons ile ayni olmali
const IS = {
  '0 3 * * *': 'senkron.yml',
  '0 5 * * *': 'paylas.yml',
};

export default {
  async scheduled(event, env) {
    const workflow = IS[event.cron];
    if (!workflow) throw new Error(`Bilinmeyen cron: ${event.cron}`);

    const res = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${workflow}/dispatches`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${env.GH_TOKEN}`,
        Accept: 'application/vnd.github+json',
        'User-Agent': 'anima-tetikleyici',
      },
      body: JSON.stringify({ ref: 'main' }),
    });

    if (res.status !== 204) throw new Error(`${workflow} tetiklenemedi: ${res.status} ${await res.text()}`);
    console.log(`${workflow} tetiklendi`);
  },
};
