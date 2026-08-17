from dxb_runway.dealer_trust import dealer_evidence, weighted_median


def offer(name,address="Dubai"):
    return {"marketSeller":{"name":name},"address":address}


def test_promoted_dealers_are_direct_and_dubai_gets_priority():
    for name in ("Park Lane","Zeus Auto","Blackline Motors"):
        tier,weight,_=dealer_evidence(offer(name));assert tier=="direct" and weight>1.25
    assert dealer_evidence(offer("GTA Cars","Abu Dhabi"))[0] == "exclude"


def test_consider_and_excluded_dealers_are_transparent():
    assert dealer_evidence(offer("Kavak"))[0]=="consider"
    assert dealer_evidence(offer("Random Motors","Al Aweer, Dubai"))[0]=="exclude"
    assert dealer_evidence(offer("Random Motors","Sharjah"))[0]=="exclude"


def test_abudhabi_is_allowed_only_for_the_matching_official_agency():
    maserati={**offer("Al Tayer Motors","Abu Dhabi"),"catalogBrand":{"name":"Maserati"}}
    wrong_brand={**offer("Al Tayer Motors","Abu Dhabi"),"catalogBrand":{"name":"Audi"}}
    assert dealer_evidence(maserati)[0]=="agency"
    assert dealer_evidence(wrong_brand)[0]=="exclude"


def test_weighted_median_prioritises_stronger_evidence():
    assert weighted_median([(100000,1),(120000,4),(300000,.5)])==120000
