# -*- coding: utf-8 -*-
"""v28 (29/10/2026) : annonce des mises a jour du site AeroClubManager dans la fenetre du traqueur.

Le site ajoute « annonce » a sa reponse a chaque paquet de telemetrie (api_tracker.php, annonce_lib.php) :
{"id", "version", "etat" (prevue | en_cours | terminee), "etape" (annonce | rappel | debut | fin | None), "debut", "fin",
 "titre", "texte", "radio"?}. Le traqueur affiche chaque etape une seule fois (une fois par annonce, rappel 15 min avant,
au debut, a la fin). La voix radio dans le simulateur est deja jouee par le programme MSFS (file des messages du site) :
le traqueur n'a rien a faire pour elle.
"""

_VUES = set()


def cle_annonce(a):
    """Cle d'affichage d'une etape (None : rien a afficher)."""
    if not isinstance(a, dict) or not a.get("etape"):
        return None
    return "%s:%s:%s" % (a.get("id"), a.get("etape"), a.get("debut") if a.get("etape") == "annonce" else "")


def texte_annonce(a):
    """Lignes a afficher pour une annonce (liste de chaines)."""
    titre = str(a.get("titre") or "Mise a jour du site AeroClubManager")
    texte = str(a.get("texte") or "").strip()
    lignes = ["", "=" * 64, "📢 " + titre]
    if texte:
        lignes.append("   " + texte)
    if a.get("etat") in ("prevue", "en_cours"):
        lignes.append("   Heure de Paris. Une mission deja commencee ne sera pas penalisee si la mise a jour coupe votre vol.")
    lignes.append("   Details : page « Journal des mises a jour » du site.")
    lignes.append("=" * 64)
    return lignes


def afficher_annonce(a, ecrire=print):
    """Affiche l'etape une seule fois. Renvoie True si quelque chose a ete affiche. Ne leve jamais d'exception."""
    try:
        cle = cle_annonce(a)
        if cle is None or cle in _VUES:
            return False
        _VUES.add(cle)
        if a.get("etape") == "rappel":   # le rappel remplace l'annonce : pas les deux d'affilee au demarrage
            _VUES.add("%s:annonce:%s" % (a.get("id"), a.get("debut")))
        for ligne in texte_annonce(a):
            ecrire(ligne)
        return True
    except Exception:
        return False
