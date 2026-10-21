"""Fictional people: names drawn by region from common given names and surnames, usernames, and e-mail addresses on
reserved domains (example.com / .example / .test) so that no address can belong to a real person."""
import numpy as np

from .config import DOMAIN, PLAYER_DOMAINS

_F = {
    'en': ('James Mary John Patricia Robert Jennifer Michael Linda David Elizabeth William Barbara Richard Susan Joseph Jessica '
           'Thomas Sarah Chris Karen Daniel Lisa Matthew Nancy Anthony Betty Mark Sandra Steven Ashley Paul Emily Andrew Donna '
           'Joshua Michelle Kevin Amanda Brian Melissa Ryan Laura Jacob Rachel Liam Olivia Noah Emma Ethan Ava Logan Mia '
           'Lucas Chloe Aiden Grace Owen Zoe Caleb Hannah Dylan Leah Nathan Ella Tyler Ruby Jack Isla Harry Amelia Oscar Freya'),
    'de': 'Lukas Anna Leon Lena Finn Mia Jonas Emma Paul Lea Felix Hannah Max Sophie Elias Marie Ben Laura Noah Julia Jan Lisa Tim Sarah',
    'fr': 'Lucas Emma Hugo Chloe Louis Lea Gabriel Manon Arthur Camille Jules Ines Adam Sarah Nathan Louise Theo Jade Raphael Alice',
    'es': 'Mateo Sofia Santiago Valentina Diego Isabella Sebastian Camila Alejandro Lucia Daniel Martina Pablo Paula Javier Elena '
          'Carlos Maria Andres Gabriela Miguel Fernanda Luis Daniela',
    'pt': 'Joao Ana Pedro Julia Gabriel Beatriz Lucas Mariana Matheus Larissa Rafael Camila Gustavo Amanda Felipe Leticia Bruno Carolina',
    'it': 'Leonardo Giulia Francesco Sofia Alessandro Aurora Lorenzo Alice Matteo Ginevra Andrea Emma Gabriele Giorgia Marco Chiara',
    'ja': 'Haruto Yui Sota Hina Yuto Aoi Riku Sakura Kaito Mei Ren Yuna Hayato Rin Takumi Saki Kenta Miyu Daiki Nanami',
    'ko': 'Minjun Seoyeon Seojun Jiwoo Dohyun Hayoon Jiho Seoa Junwoo Jiyoon Hyunwoo Minseo Jihoon Yuna Taeyang Soyeon',
    'pl': 'Jakub Zuzanna Szymon Julia Antoni Maja Jan Zofia Filip Hanna Kacper Amelia Piotr Natalia Michal Wiktoria',
    'nl': 'Daan Emma Sem Julia Lucas Mila Levi Tess Finn Sophie Milan Zoe Jesse Sara Thijs Eva',
    'sv': 'William Alice Oscar Maja Lucas Elsa Hugo Astrid Elias Wilma Alexander Freja Liam Ebba Oliver Agnes',
    'tr': 'Yusuf Zeynep Eymen Elif Mustafa Defne Emir Asel Omer Azra Ali Ecrin Ahmet Nehir Mehmet Ayse',
    'id': 'Budi Siti Agus Dewi Andi Rina Rizky Putri Dimas Ayu Fajar Indah Hendra Lestari Yoga Wulan',
    'th': 'Somchai Somying Anan Malee Kittisak Pimchanok Narong Siriporn Thanakorn Kanokwan Prasert Sasithorn',
    'vi': 'Minh Linh Huy Trang Nam Thao Duc Ngoc Tuan Hoa Quang Mai Long Lan Khanh Huong',
    'ar': 'Mohammed Fatima Abdullah Noura Omar Sara Faisal Reem Khalid Lama Saud Hessa Turki Maha Yousef Dana',
}
_L = {
    'en': ('Smith Johnson Williams Brown Jones Miller Davis Wilson Anderson Taylor Thomas Moore Martin Jackson Thompson White '
           'Harris Clark Lewis Robinson Walker Young Allen King Wright Scott Green Baker Adams Nelson Hill Campbell Mitchell '
           'Roberts Carter Phillips Evans Turner Parker Collins Edwards Stewart Morris Murphy Cook Rogers Morgan Cooper Reed '
           'Bailey Bell Kelly Howard Ward Cox Richardson Wood Watson Brooks Bennett Gray Hughes Price Sanders Myers Long Ross Foster'),
    'de': 'Muller Schmidt Schneider Fischer Weber Meyer Wagner Becker Schulz Hoffmann Koch Richter Klein Wolf Neumann Schwarz Braun Zimmermann',
    'fr': 'Martin Bernard Dubois Thomas Robert Richard Petit Durand Leroy Moreau Simon Laurent Lefebvre Michel Garcia David Bertrand Roux',
    'es': 'Garcia Rodriguez Martinez Hernandez Lopez Gonzalez Perez Sanchez Ramirez Torres Flores Rivera Gomez Diaz Cruz Morales Reyes Ortiz',
    'pt': 'Silva Santos Oliveira Souza Rodrigues Ferreira Alves Pereira Lima Gomes Costa Ribeiro Martins Carvalho Almeida Lopes Araujo',
    'it': 'Rossi Russo Ferrari Esposito Bianchi Romano Colombo Ricci Marino Greco Bruno Gallo Conti DeLuca Costa Giordano Mancini',
    'ja': 'Sato Suzuki Takahashi Tanaka Watanabe Ito Yamamoto Nakamura Kobayashi Kato Yoshida Yamada Sasaki Yamaguchi Matsumoto Inoue',
    'ko': 'Kim Lee Park Choi Jung Kang Cho Yoon Jang Lim Han Oh Seo Shin Kwon Hwang',
    'pl': 'Nowak Kowalski Wisniewski Wojcik Kowalczyk Kaminski Lewandowski Zielinski Szymanski Wozniak Dabrowski Kozlowski',
    'nl': 'DeJong Jansen DeVries VanDenBerg VanDijk Bakker Janssen Visser Smit Meijer DeBoer Mulder',
    'sv': 'Andersson Johansson Karlsson Nilsson Eriksson Larsson Olsson Persson Svensson Gustafsson Pettersson Jonsson',
    'tr': 'Yilmaz Kaya Demir Sahin Celik Yildiz Yildirim Ozturk Aydin Ozdemir Arslan Dogan',
    'id': 'Santoso Wijaya Saputra Hidayat Kusuma Pratama Nugroho Setiawan Wibowo Susanto Halim Gunawan',
    'th': 'Saetang Srisuk Chaiyaporn Wongsawat Rattanakorn Bunnag Charoensuk Thongchai Kaewmanee Phongphan',
    'vi': 'Nguyen Tran Le Pham Hoang Phan Vu Vo Dang Bui Do Ho',
    'ar': 'AlSaud AlHarbi AlQahtani AlGhamdi AlOtaibi AlDosari AlShehri AlZahrani AlMutairi AlAnazi AlShammari AlQurashi',
}
FIRST = {k: v.split() for k, v in _F.items()}
LAST = {k: v.split() for k, v in _L.items()}
LANG_GROUP = {'en': 'en', 'de': 'de', 'fr': 'fr', 'es': 'es', 'pt': 'pt', 'it': 'it', 'ja': 'ja', 'ko': 'ko', 'pl': 'pl', 'nl': 'nl',
              'sv': 'sv', 'tr': 'tr', 'id': 'id', 'th': 'th', 'vi': 'vi', 'ar': 'ar'}
WORDS = ('shadow pixel storm fox wolf nova blaze echo frost lunar dragon ninja rogue ember viper comet raven titan spark '
         'orbit falcon ghost mango cookie panda tiger bolt jade onyx quest hero zen lucky sunny dusty rusty misty').split()


def people(rng, langs):
    """langs: array of language codes -> (first, last) arrays."""
    langs = np.asarray(langs)
    first = np.empty(len(langs), dtype=object)
    last = np.empty(len(langs), dtype=object)
    for lg in np.unique(langs):
        idx = np.nonzero(langs == lg)[0]
        g = LANG_GROUP.get(lg, 'en')
        first[idx] = np.asarray(FIRST[g], dtype=object)[rng.integers(0, len(FIRST[g]), len(idx))]
        last[idx] = np.asarray(LAST[g], dtype=object)[rng.integers(0, len(LAST[g]), len(idx))]
    return first, last


def player_emails(rng, first, last, ids):
    styles = rng.integers(0, 4, len(ids))
    doms = np.asarray(PLAYER_DOMAINS, dtype=object)[rng.integers(0, len(PLAYER_DOMAINS), len(ids))]
    out = np.empty(len(ids), dtype=object)
    for i in range(len(ids)):
        f, la, n = first[i].lower(), last[i].lower(), ids[i]
        s = styles[i]
        local = f'{f}.{la}{n % 1000}' if s == 0 else f'{f[0]}{la}{n % 10000}' if s == 1 else f'{f}{n % 100000}' if s == 2 else f'{la}.{f}.{n % 997}'
        out[i] = f'{local}.{n}@{doms[i]}'
    return out


def usernames(rng, ids):
    a = np.asarray(WORDS, dtype=object)[rng.integers(0, len(WORDS), len(ids))]
    b = np.asarray(WORDS, dtype=object)[rng.integers(0, len(WORDS), len(ids))]
    return np.array([f'{x.capitalize()}{y.capitalize()}{i % 10000}' for x, y, i in zip(a, b, ids)], dtype=object)


def staff_email(first, last, n=None):
    return f'{first.lower()}.{last.lower()}{"" if not n else n}@{DOMAIN}'
