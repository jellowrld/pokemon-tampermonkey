import requests
import json
import time
import os
import threading
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed

OUTPUT_FILE = 'pokemon_data.json'
TEMP_FILE = 'pokemon_data_tmp.json'
LOG_FILE = 'logs.txt'
THREAD_COUNT = 5
lock = threading.Lock()

def log_error(message):
    with lock:
        with open(LOG_FILE, 'a') as log:
            log.write(message + '\n')

def load_existing_data():
    if not os.path.exists(OUTPUT_FILE):
        return set()
    try:
        with open(OUTPUT_FILE, 'r') as f:
            data = json.load(f)
            return set(p['name'] for p in data if 'id' in p and 'stats' in p and 'types' in p)
    except json.JSONDecodeError:
        return set()

def append_to_temp(data):
    with lock:
        with open(TEMP_FILE, 'a') as f:
            json.dump(data, f, indent=2)
            f.write(',\n')

def finalize_file():
    with open(TEMP_FILE, 'r') as temp, open(OUTPUT_FILE, 'w') as final:
        lines = temp.readlines()
        if lines:
            final.write('[\n')
            final.writelines(lines[:-1])
            final.write(lines[-1].rstrip(',\n') + '\n')
            final.write(']\n')
    os.remove(TEMP_FILE)

def sprite_exists(url):
    try:
        response = requests.head(url, timeout=5)
        return response.status_code == 200
    except requests.RequestException:
        return False

def get_showdown_sprites(pokemon_data):
    base_url = "https://play.pokemonshowdown.com/sprites/ani/"
    shiny_url = "https://play.pokemonshowdown.com/sprites/ani-shiny/"

    name = pokemon_data['name'].lower()
    form_name = pokemon_data['forms'][0]['name'].lower()
    form_name_clean = form_name.replace('-', '')

    sprite = None
    shiny = None

    # Check form-specific shiny first
    if sprite_exists(shiny_url + f"{form_name_clean}.gif"):
        shiny = shiny_url + f"{form_name_clean}.gif"
    elif sprite_exists(shiny_url + f"{name}.gif"):
        shiny = shiny_url + f"{name}.gif"

    # Check form-specific regular
    if sprite_exists(base_url + f"{form_name_clean}.gif"):
        sprite = base_url + f"{form_name_clean}.gif"
    elif sprite_exists(base_url + f"{name}.gif"):
        sprite = base_url + f"{name}.gif"

    return {'default': sprite, 'shiny': shiny}

def fetch_pokemon(pokemon):
    try:
        pokemon_response = requests.get(pokemon['url'])
        pokemon_data = pokemon_response.json()

        species_response = requests.get(pokemon_data['species']['url'])
        species_data = species_response.json()

        evolution_chain = []
        if species_data.get('evolution_chain'):
            evo_response = requests.get(species_data['evolution_chain']['url'])
            if evo_response.status_code == 200:
                evo_data = evo_response.json()
                chain = evo_data['chain']
                while chain:
                    evolution_chain.append(chain['species']['name'])
                    if chain['evolves_to']:
                        chain = chain['evolves_to'][0]
                    else:
                        break

        sprites = get_showdown_sprites(pokemon_data)

        data = {
            'id': pokemon_data['id'],
            'name': pokemon_data['name'],
            'height': pokemon_data['height'],
            'weight': pokemon_data['weight'],
            'base_experience': pokemon_data['base_experience'],
            'types': [t['type']['name'] for t in pokemon_data['types']],
            'abilities': [a['ability']['name'] for a in pokemon_data['abilities']],
            'stats': {s['stat']['name']: s['base_stat'] for s in pokemon_data['stats']},
            'sprites': sprites,
            'forms': [form['name'] for form in pokemon_data['forms']],
            'evolution_chain': evolution_chain,
            'generation': species_data['generation']['name'],
            'habitat': species_data['habitat']['name'] if species_data['habitat'] else None,
            'color': species_data['color']['name'],
            'shape': species_data['shape']['name'],
            'is_legendary': species_data['is_legendary'],
            'is_mythical': species_data['is_mythical'],
            'flavor_text_entries': [
                entry['flavor_text'] for entry in species_data['flavor_text_entries']
                if entry['language']['name'] == 'en'
            ]
        }

        append_to_temp(data)
        return data['name']
    except Exception as e:
        log_error(f"Error fetching {pokemon['name']}: {e}")
        return None

def fetch_all_pokemon_data():
    base_url = 'https://pokeapi.co/api/v2/pokemon'
    params = {'limit': 100000, 'offset': 0}
    response = requests.get(base_url, params=params)
    response.raise_for_status()
    pokemon_list = response.json()['results']

    saved_pokemon = load_existing_data()
    print(f"Skipping {len(saved_pokemon)} Pokémon already saved.")

    if os.path.exists(TEMP_FILE):
        os.remove(TEMP_FILE)

    with ThreadPoolExecutor(max_workers=THREAD_COUNT) as executor:
        futures = {
            executor.submit(fetch_pokemon, p): p['name']
            for p in pokemon_list if p['name'] not in saved_pokemon
        }

        for future in tqdm(as_completed(futures), total=len(futures), desc="Fetching"):
            name = future.result()
            if name:
                print(f"Saved {name}")

    finalize_file()
    print(f"All data saved to {OUTPUT_FILE}")

if __name__ == '__main__':
    fetch_all_pokemon_data()