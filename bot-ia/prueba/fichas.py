"""
FICHAS DE CONVERSACIÓN del asesor de la licitación 85-34-LR25.

Cada ficha es cómo pensaría un jefe de mantención que conoce las bases: qué preguntar para entender el caso
y a qué conclusión se llega según la respuesta. La IA (Qwen) conversa con estas fichas: entiende lo que le
contestas y lo dice con sus palabras, pero la CONCLUSIÓN y las CITAS salen de aquí (así no inventa).

Cómo se lee una ficha:
  claves       palabras que hacen que se use esta ficha
  preguntas    lo que se pregunta para entender el caso; cada opción tiene una descripción (para la IA) y
               palabras que la reconocen. "cuando" = solo se pregunta si ya se sabe eso.
  conclusiones en orden; gana la primera que calza con lo que ya se sabe. Si a la primera que todavía puede
               calzar le falta un dato, se pregunta ese dato. La última no exige nada (es el "depende").
  citas        documento, página y el comienzo de la frase que se copia TAL CUAL al explicar el porqué
               ("tipo": solo para colegio o solo para jardín).
  criterio     True = no lo dice la licitación con esas palabras: es criterio interno; se avisa al explicar.

Datos de todas las fichas:
  tipo   colegio (JUNAEB) o jardin (JUNJI/INTEGRA): se saca del nombre del establecimiento o se pregunta.
  lugar  dentro (cocina, bodega, patio de servicio, baño de manipuladoras) / fuera; si no se dice, "dentro".

Para corregir una ficha: dime qué está mal (o escríbelo en el grupo Prueba: "está mal, …") y la ajusto.
"""

NOMBRES_DOC = {
    "BASES": "Bases licitación 85-34-LR25 (RAF N°44)",
    "SGC": "Manual Técnico SGC PAE (jun. 2025)",
    "DTMANT": "DT Mantención de infraestructura, equipamiento y artefactos (JUNJI-INTEGRA)",
}


def C(doc, pag, inicio, titulo="", tipo=None, texto=None):
    return {"doc": doc, "pag": pag, "inicio": inicio, "titulo": titulo, "tipo": tipo, "texto": texto}


# ---------------------------------------------------------------- citas que se repiten
CAUSADO_SOSER = [
    C("BASES", 220, "Cuando se comprueben deterioros", "4.2.2 Infraestructura de responsabilidad del prestador", "colegio"),
    C("BASES", 279, "El Prestador que ejerza esta opción", "6.7.5.2 Responsabilidades del Prestador (jardines)", "jardin"),
]
MANTENER_OPERATIVO = [
    C("BASES", 216, "El prestador deberá mantener operativas", "4.2.2 Infraestructura de responsabilidad del prestador", "colegio"),
]
ESTRUCTURAL_SOSTENEDOR = [
    C("BASES", 216, "Realizar los trabajos que involucren cambios estructurales de la infraestructura",
      "4.2.1 Infraestructura de responsabilidad del sostenedor", "colegio"),
    C("BASES", 279, "Los trabajos que comprometan áreas estructurales", "6.7.5.2 (jardines)", "jardin"),
]
AREAS_DEL_SERVICIO = [
    C("BASES", 215, "El sostenedor debe poner a disposición del prestador", "4.2 Infraestructura", "colegio"),
    C("BASES", 279, "El Prestador podrá hacer uso sin costo de la infraestructura", "6.7.5.2 (jardines)", "jardin"),
]
NO_LIBERA_SOSTENEDOR = C("BASES", 220, "Sin perjuicio de lo ya indicado, este Título", "4.2.2 (cierre)", "colegio")
ROBOS = [
    C("BASES", 213, "Los robos, deterioros y daños", "3.9 Robos o actos delictivos"),
    C("BASES", 213, "Es responsabilidad del Prestador tomar todas las medidas", "3.9 Robos o actos delictivos"),
]
SGC_VENTANAS = C("SGC", 51, "Nota: con relación a las ventanas", "5.2.3 Paredes, tabiques, techos y puertas")
SGC_HERMETICIDAD = C("SGC", 52, "Todas las ventanas externas, aberturas de ventilación", "5.2.4 Hermeticidad")

NOSE = ("no se sabe / no tengo idea",
        r"\b(no se|nose|ni idea|no sabemos|no tengo idea|nadie sabe|desconoc\w*|no me dijeron|no se sabe|ni pico idea)\b")

GLOBAL = {
    "tipo": {"texto": "¿Es colegio JUNAEB o jardín JUNJI / INTEGRA?",
             "opciones": {"jardin": ("jardín infantil o sala cuna (JUNJI o INTEGRA)",
                                     r"\b(jardin\w*|sala cuna|parvul\w*|junji|integra)\b"),
                          "colegio": ("colegio, escuela o liceo (JUNAEB)",
                                      r"\b(colegio|escuela|liceo|junaeb|basica|media|internado)\b")}},
    "lugar": {"texto": "¿Está dentro de la cocina, bodega o baño de manipuladoras, o en otra parte del establecimiento?",
              "defecto": "dentro",
              "opciones": {"fuera": ("fuera de los recintos del servicio de alimentación",
                                     r"\b(sala de clases|salas? de (los )?(ninos|alumnos)|pasillo\w*|oficina\w*|gimnasio|"
                                     r"porteria|bano\w* de (los )?(alumnos|ninos|ninas|profes\w*|apoderados)|"
                                     r"patio de juegos|patio del colegio|biblioteca|direccion|otra parte del colegio)\b"),
                           "dentro": ("dentro de cocina, bodega, patio de servicio o baño de manipuladoras",
                                      r"\b(cocina|bodega|despensa|patio de servicio|bano de (las )?manipuladoras|esclusa)\b")}},
}

FUERA_DEL_SERVICIO = {
    "id": "fuera", "si": {"lugar": "fuera"}, "quien": "el establecimiento",
    "corto": "Si está fuera de la cocina, bodega, patio de servicio o baño de manipuladoras, no es nuestro: le toca al "
             "establecimiento. Nosotros mantenemos solo las áreas que nos entregaron para el servicio de alimentación.",
    "hacer": "Avisarle al director por escrito para que lo vea el sostenedor.",
    "citas": AREAS_DEL_SERVICIO + MANTENER_OPERATIVO,
}


# ================================================================ FICHAS
TEMAS = [
    # ------------------------------------------------------------ VIDRIO / VENTANA
    {
        "id": "vidrio", "nombre": "vidrio roto",
        "claves": r"\b(vidrio\w*|ventana\w*|cristal\w*|quebrad\w*|trizad\w*|trizadura\w*|quebrazon\w*)\b",
        "preguntas": [
            {"id": "causa",
             "texto": "¿Y sabes de casualidad cómo se rompió? ¿Fue alguien de nosotros (manipuladora, técnico), "
                      "un golpe de afuera (alumnos, pelotazo, robo) o se trizó solo con el tiempo?",
             "opciones": {
                 "soser": ("lo rompió personal de SOSER (manipuladora, técnico, maestro nuestro)",
                           r"\b(manipulador\w*|nosotr\w*|nuestr\w*|tecnico\w*|maestro\w*|se nos|soser|personal de la cocina|"
                           r"carro|con (una|un|el|la) (olla|fondo|bandeja|escalera))\b"),
                 "terceros": ("golpe de terceros: alumnos, pelotazo, robo o vandalismo",
                              r"\b(alumn\w*|estudiant\w*|nin[oa]s|cabro\w*|pelota\w*|robo\w*|robaron|entraron|vandal\w*|"
                              r"piedra\w*|piedrazo|apoderad\w*|ladron\w*|delincuen\w*|de afuera|desde afuera|externo\w*)\b"),
                 "estructura": ("el marco o el muro está malo: podrido, suelto, con grieta",
                                r"\b(marco\w*|podrid\w*|muro\w*|pared\w*|estructur\w*|grieta\w*|se movio|se cayo el marco|"
                                r"bisagra\w*|oxidad\w*)\b"),
                 "desgaste": ("se trizó o se soltó solo, por desgaste o el tiempo",
                              r"\b(solo|sola|tiempo|viej[oa]|desgast\w*|masilla|silicona|calor|temperatura|"
                              r"se solto|antiguo|de a poco|nadie)\b"),
                 "nose": NOSE}},
        ],
        "conclusiones": [
            FUERA_DEL_SERVICIO,
            {"id": "soser", "si": {"causa": "soser"}, "quien": "SOSER",
             "corto": "Entonces nos toca a nosotros: si lo rompió alguien de SOSER, hay que reponerlo al tiro y a nuestro costo.",
             "hacer": "Taparlo provisorio para que no entren plagas ni caigan astillas, y reponer el vidrio con lámina antiquebrazo.",
             "citas": CAUSADO_SOSER + [SGC_VENTANAS]},
            {"id": "terceros", "si": {"causa": "terceros"}, "quien": "el sostenedor (con denuncia o carta)",
             "corto": "Si fue un golpe de afuera (alumnos, robo o vandalismo), no lo causamos nosotros: hay que dejarlo "
                      "denunciado o con carta del colegio y gestionar con el sostenedor que lo repare. Lo que sí nos toca es "
                      "que la cocina siga funcionando, así que conviene taparlo provisorio mientras.",
             "nota": "Las bases no dicen con esas palabras quién paga un vidrio roto por terceros: dicen que se denuncia, "
                     "que SOSER asegura la continuidad y que el sostenedor no queda liberado de sus obligaciones de infraestructura.",
             "hacer": "Pedir al director una carta o la constancia de denuncia, tapar provisorio y dejar foto en Datácora.",
             "citas": ROBOS + [NO_LIBERA_SOSTENEDOR, SGC_VENTANAS]},
            {"id": "estructura", "si": {"causa": "estructura"}, "quien": "el sostenedor",
             "corto": "Si el problema de fondo es el marco o el muro (podrido, suelto, con grieta), eso es estructura y le toca al sostenedor.",
             "hacer": "Informarlo por escrito al director con fotos; mientras, asegurar que la ventana selle (plagas) y no caigan vidrios.",
             "citas": ESTRUCTURAL_SOSTENEDOR + [SGC_HERMETICIDAD]},
            {"id": "desgaste_colegio", "si": {"causa": "desgaste", "tipo": "colegio"}, "quien": "SOSER",
             "corto": "En colegio JUNAEB nos toca a nosotros: tenemos que mantener operativas, a nuestro costo, todas las áreas "
                      "que nos entregaron, y un vidrio trizado por el tiempo entra en esa mantención.",
             "hacer": "Reponer el vidrio (idealmente con lámina antiquebrazo) y registrarlo en la matriz de riesgo / Datácora.",
             "citas": MANTENER_OPERATIVO + [SGC_VENTANAS]},
            {"id": "desgaste_jardin", "si": {"causa": "desgaste", "tipo": "jardin"}, "quien": "JUNJI / INTEGRA (sostenedor)",
             "corto": "En jardín cambia la cosa: nosotros reparamos lo que se deteriora por nuestro personal o por una mala "
                      "mantención nuestra. Si el vidrio se trizó solo con el tiempo, le corresponde al sostenedor, que es el dueño del inmueble.",
             "hacer": "Avisar a la directora por escrito y a la Dirección Regional; mientras, que la ventana selle y no haya riesgo de astillas.",
             "citas": [C("BASES", 279, "El Prestador que ejerza esta opción", "6.7.5.2 Responsabilidades del Prestador (jardines)"),
                       SGC_VENTANAS]},
            {"id": "depende", "si": {}, "quien": "depende de cómo se rompió",
             "corto": "Todavía no se puede decir: si lo rompió alguien nuestro, nos toca; si fue un golpe de afuera o un robo, "
                      "se denuncia y se gestiona con el sostenedor; si es el marco o el muro, es del sostenedor. Yo le "
                      "preguntaría a las manipuladoras y al director qué pasó.",
             "hacer": "Mientras se aclara: tapar provisorio y sacar fotos.",
             "citas": CAUSADO_SOSER + ROBOS[:1] + ESTRUCTURAL_SOSTENEDOR + [SGC_VENTANAS]},
        ],
    },

    # ------------------------------------------------------------ EXTRACTOR / CAMPANA
    {
        "id": "extractor", "nombre": "extractor",
        "claves": r"\b(extractor\w*|campana\w*|ventilador\w*|ductos?|extraccion|chimenea\w*|gorro)\b",
        "preguntas": [
            {"id": "ubic",
             "texto": "¿Cuál extractor es? ¿El de la cocina que alcanzamos desde abajo (la campana o un extractor de muro o "
                      "ventana), uno que está en el techo, o un extractor industrial alejado de la cocina?",
             "opciones": {
                 "ducto": ("hay que abrir un hoyo o abertura en el muro o techo para el ducto",
                           r"\b(abertura\w*|hoyo|perfor\w*|orificio\w*|romper el muro|hacer (un|el) (hoyo|pase)|pasada)\b"),
                 "lejos": ("un extractor industrial o de otra parte del edificio, alejado de la cocina",
                           r"\b(industrial\w*|lejos|alejad\w*|otro edificio|gimnasio|comedor|salas?|otra parte|otro lado|"
                           r"del colegio|del jardin|no es de la cocina|bano\w*)\b"),
                 "techo": ("uno que está en el techo",
                           r"\b(techo|azotea|arriba|entretecho|techumbre|cubierta|tejado|altura|loza|losa)\b"),
                 "cocina": ("el de la cocina, que se alcanza desde abajo (campana, extractor de muro o ventana)",
                            r"\b(campana|de la cocina|en la cocina|abajo|muro|pared|ventana|sobre (la cocina|los fogones|el fogon)|"
                            r"alcanzamos|de muro|chico|el nuestro)\b"),
                 "nose": NOSE}},
            {"id": "sirve", "cuando": {"ubic": "techo"},
             "texto": "¿Y ese del techo es el motor de la campana de la cocina, o es de otra parte del edificio?",
             "opciones": {
                 "otro": ("es de otra parte del edificio, no de la campana de la cocina",
                          r"\b(otra parte|edificio|bano\w*|comedor|gimnasio|sala\w*|no es de la (cocina|campana)|del colegio|otro)\b"),
                 "campana": ("es el motor / extractor de la campana de la cocina",
                             r"\b(campana|cocina|de la cocina|el de la campana|motor de la campana|nuestro|si)\b"),
                 "nose": NOSE}},
        ],
        "conclusiones": [
            {"id": "ducto", "si": {"ubic": "ducto"}, "quien": "el sostenedor (la abertura)",
             "corto": "Abrir el muro o la losa para el ducto le toca al sostenedor, porque es un trabajo de infraestructura. "
                      "Si el colegio no tiene plata o tiempo, tiene que declararlo por escrito y acordar con nosotros quién paga y en qué plazo.",
             "nota": "En jardines, una vez hecha la abertura, instalar y mantener el ducto (con su gorro) y el extractor es nuestro.",
             "hacer": "Pedir por escrito al director que gestione la abertura.",
             "citas": [C("BASES", 216, "Trabajos en infraestructura", "4.2.1 Infraestructura de responsabilidad del sostenedor", "colegio"),
                       C("BASES", 216, "En caso de que el establecimiento educacional no cuente con los recursos", "4.2.1", "colegio"),
                       C("BASES", 278, "Orificios para extracción de aire", "6.7.5.1 Responsabilidades de JUNJI e Integra", "jardin"),
                       C("DTMANT", 6, "La instalación (incluye gorro", "Campana extractora de vapores", "jardin",
                         texto="La instalación (incluye gorro para tubo de acero campana), mantención y/o limpieza de ductos "
                               "de ventilación (interior y exterior) y extractores de vapores, así como la limpieza y/o "
                               "recambio de filtros, será de responsabilidad del Prestador.")]},
            {"id": "lejos", "si": {"ubic": "lejos"}, "quien": "el establecimiento",
             "corto": "Ese no es nuestro: es del establecimiento. Nosotros vemos la campana y los extractores de la cocina, que "
                      "son artefactos del servicio de alimentación; un extractor industrial o de otra parte del edificio no entra ahí.",
             "criterio": True,
             "hacer": "Avisarle al director para que lo vea el sostenedor.",
             "citas": [C("BASES", 221, "El prestador deberá considerar, al menos", "4.3.1 Mobiliario, equipamiento y artefactos")]
                      + AREAS_DEL_SERVICIO},
            {"id": "techo_otro", "si": {"ubic": "techo", "sirve": "otro"}, "quien": "el establecimiento",
             "corto": "Si el del techo no es el de la campana de la cocina, no es nuestro: es una instalación del edificio y la ve el sostenedor.",
             "criterio": True,
             "hacer": "Avisarle al director.",
             "citas": [C("BASES", 221, "El prestador deberá considerar, al menos", "4.3.1 Mobiliario, equipamiento y artefactos")]
                      + AREAS_DEL_SERVICIO},
            {"id": "techo_campana_jardin", "si": {"ubic": "techo", "sirve": "campana", "tipo": "jardin"}, "quien": "SOSER",
             "corto": "En jardín sí nos toca aunque esté en el techo: el documento de mantención de JUNJI-INTEGRA pone los ductos "
                      "(por dentro y por fuera) y los extractores de vapores de la campana a cargo nuestro.",
             "hacer": "Coordinar con la directora el trabajo en altura (con las medidas de seguridad) y dejarlo registrado.",
             "citas": [C("DTMANT", 6, "La instalación (incluye gorro", "Campana extractora de vapores",
                         texto="La instalación (incluye gorro para tubo de acero campana), mantención y/o limpieza de ductos "
                               "de ventilación (interior y exterior) y extractores de vapores, así como la limpieza y/o "
                               "recambio de filtros, será de responsabilidad del Prestador."),
                       C("DTMANT", 6, "Plazo para mantención", "Campana extractora de vapores",
                         texto="Plazo para mantención: una vez al año o cada vez que se requiera.")]},
            {"id": "techo_campana_colegio", "si": {"ubic": "techo", "sirve": "campana", "tipo": "colegio"},
             "quien": "SOSER (lo más probable, ojo)",
             "corto": "Ojo con este: en colegio la campana es un artefacto nuestro y el SGC nos pide asegurar que el sistema de "
                      "extracción funcione. Si ese motor del techo es el de nuestra campana, lo más seguro es que nos lo cobren a "
                      "nosotros, aunque esté arriba. Lo que sí es del sostenedor es la abertura o el pase del ducto.",
             "nota": "Las bases no separan el extractor de techo del de abajo: hablan de la campana y del sistema de extracción completo.",
             "hacer": "Si lo vamos a ver nosotros, coordinar trabajo en altura con el colegio. Si crees que no nos toca, déjalo por escrito con el director.",
             "citas": [C("BASES", 221, "El prestador deberá considerar, al menos", "4.3.1 Mobiliario, equipamiento y artefactos"),
                       C("SGC", 52, "La persona designada por el prestador debe asegurar que se repare", "5.2.5 Ventilación"),
                       C("BASES", 216, "Trabajos en infraestructura", "4.2.1 (aberturas para ductos: sostenedor)")]},
            {"id": "cocina", "si": {"ubic": "cocina"}, "quien": "SOSER",
             "corto": "Ese es nuestro: la campana y los extractores de la cocina son artefactos del servicio, y tenemos que tenerlos "
                      "funcionando y limpios. Si falla, se repara; si está con grasa, se limpia.",
             "hacer": "Revisar motor, aspas y filtros; limpiar grasa. En jardines, una campana sucia o sin funcionar es falta GRAVE en la supervisión C1-A.",
             "citas": [C("BASES", 221, "El prestador deberá considerar, al menos", "4.3.1 Mobiliario, equipamiento y artefactos"),
                       C("SGC", 52, "La persona designada por el prestador debe asegurar que se repare", "5.2.5 Ventilación"),
                       C("BASES", 111, "En relación a los artefactos de la cocina", "16.1.10.1 Acta de supervisión C1-A JUNJI-INTEGRA, ítem 28: falta GRAVE", "jardin"),
                       C("DTMANT", 6, "La instalación (incluye gorro", "Campana extractora de vapores", "jardin",
                         texto="La instalación (incluye gorro para tubo de acero campana), mantención y/o limpieza de ductos "
                               "de ventilación (interior y exterior) y extractores de vapores, así como la limpieza y/o "
                               "recambio de filtros, será de responsabilidad del Prestador.")]},
            {"id": "depende", "si": {}, "quien": "depende de cuál extractor es",
             "corto": "Depende de cuál sea: la campana y los extractores de la cocina son nuestros; uno industrial o de otra parte "
                      "del edificio es del establecimiento; y abrir muros para ductos es del sostenedor.",
             "hacer": "Mándame una foto o dime dónde está y lo vemos.",
             "citas": [C("BASES", 221, "El prestador deberá considerar, al menos", "4.3.1"),
                       C("BASES", 216, "Trabajos en infraestructura", "4.2.1")]},
        ],
    },

    # ------------------------------------------------------------ TECHO / GOTERA
    {
        "id": "gotera", "nombre": "gotera o filtración",
        "claves": r"\b(gotera\w*|gotea\w*|filtra\w*|llueve|lluvia|techo|cielo|humedad|mancha\w* de agua|aposamiento)\b",
        "preguntas": [
            {"id": "origen",
             "texto": "¿De dónde viene el agua? ¿Del techo cuando llueve, o de una cañería o conexión de la cocina (llave, flexible, desagüe, calefón)?",
             "opciones": {
                 "caneria": ("de una cañería, llave, flexible, desagüe o conexión de la cocina",
                             r"\b(caneria\w*|llave\w*|flexible\w*|conexion\w*|desague\w*|lavaplatos|lavafondos|calefon|sifon\w*|"
                             r"fitting|tuberia\w*|matriz|pvc)\b"),
                 "lluvia": ("del techo / cubierta cuando llueve",
                            r"\b(llueve|lluvia|techo|techumbre|canaleta\w*|teja\w*|plancha\w*|de arriba|cubierta|cielo|losa)\b"),
                 "nose": NOSE}},
        ],
        "conclusiones": [
            FUERA_DEL_SERVICIO,
            {"id": "caneria", "si": {"origen": "caneria"}, "quien": "SOSER",
             "corto": "Si viene de una cañería o conexión dentro de la cocina, nos toca a nosotros: las conexiones interiores de agua "
                      "y sus filtraciones son nuestras.",
             "hacer": "Reparar la filtración y después dejar el cielo o muro sin hongos ni descascarado (pintura antihongos también es nuestra).",
             "citas": [C("BASES", 217, "El prestador será responsable de reparar todas las filtraciones", "4.2.2 Red de agua", "colegio"),
                       C("BASES", 217, "Trabajos de pintura anual", "4.2.2 Pintura", "colegio"),
                       C("BASES", 281, "El Prestador es responsable de las conexiones de los artefactos", "6.7.6 (jardines)", "jardin")]},
            {"id": "lluvia", "si": {"origen": "lluvia"}, "quien": "el sostenedor",
             "corto": "Si entra por el techo cuando llueve, es estructura: le toca al sostenedor arreglar la cubierta. "
                      "Nosotros nos encargamos después de dejar el cielo limpio, sin hongos y pintado.",
             "hacer": "Avisar al director por escrito con fotos; proteger alimentos y equipos mientras.",
             "citas": ESTRUCTURAL_SOSTENEDOR + [C("BASES", 217, "Trabajos de pintura anual", "4.2.2 Pintura", "colegio")]},
            {"id": "depende", "si": {}, "quien": "depende de dónde viene el agua",
             "corto": "Depende de dónde venga: si es del techo, es del sostenedor; si es una cañería o conexión de la cocina, es nuestra.",
             "hacer": "Revisar si gotea solo cuando llueve o también en seco.",
             "citas": ESTRUCTURAL_SOSTENEDOR + [C("BASES", 217, "El prestador será responsable de reparar todas las filtraciones", "4.2.2", "colegio")]},
        ],
    },

    # ------------------------------------------------------------ ELECTRICIDAD
    {
        "id": "electricidad", "nombre": "electricidad",
        "claves": r"\b(luz|electric\w*|enchufe\w*|interruptor\w*|automatico\w*|tablero\w*|foco\w*|tubos?|luminaria\w*|"
                  r"ampolleta\w*|cable\w*|trifasic\w*|empalme|apagon|sin energia|corte de energia)\b",
        "preguntas": [
            {"id": "alcance",
             "texto": "¿Es algo de la cocina (enchufe, foco, interruptor, el automático de la cocina) o se cortó la luz en todo "
                      "el establecimiento (empalme, tablero general, corte de la compañía)?",
             "opciones": {
                 "general": ("corte en todo el establecimiento: empalme, medidor, tablero general o compañía eléctrica",
                             r"\b(todo el (colegio|jardin|establecimiento|sector)|empalme|tablero general|medidor|poste|enel|cge|"
                             r"compania|toda la cuadra|sector|general|apagon)\b"),
                 "interior": ("algo dentro de la cocina: enchufe, foco, interruptor, automático o cable de la cocina",
                              r"\b(enchufe\w*|foco\w*|tubos?|ampolleta\w*|interruptor\w*|luminaria\w*|automatico\w*|cable\w*|"
                              r"en la cocina|de la cocina|solo la cocina|bodega|tablero de la cocina)\b"),
                 "nose": NOSE}},
        ],
        "conclusiones": [
            {"id": "general", "si": {"alcance": "general"}, "quien": "el sostenedor (y nosotros la cadena de frío)",
             "corto": "Si es corte en todo el establecimiento o del empalme, el suministro es del sostenedor. Lo que nos toca a "
                      "nosotros es cuidar la cadena de frío y que el servicio siga, con nuestro plan de contingencia.",
             "hacer": "Revisar refrigeradores (no abrir), avisar al director y activar contingencia si se alarga.",
             "citas": [C("BASES", 215, "Suministro de electricidad", "4.2.1 Servicios básicos del sostenedor", "colegio"),
                       C("BASES", 217, "Ante la eventualidad de cortes de luz durante los fines de semana", "4.2.2 Red de electricidad", "colegio"),
                       C("BASES", 278, "Las instituciones son responsables de las respectivas conexiones", "6.7.5.1 (jardines)", "jardin")]},
            {"id": "interior", "si": {"alcance": "interior"}, "quien": "SOSER",
             "corto": "Eso es nuestro: enchufes, interruptores, focos, protecciones y cables dentro de la cocina los reparamos "
                      "nosotros, siempre con personal SEC.",
             "nota": "En jardín: foco quemado se repone en máximo 5 días hábiles, y no podemos modificar la instalación eléctrica del establecimiento.",
             "hacer": "Mandar técnico SEC; nada de alargadores múltiples.",
             "citas": [C("BASES", 217, "Red de electricidad: El prestador será responsable", "4.2.2 Red de electricidad", "colegio"),
                       C("BASES", 281, "El Prestador es responsable de la mantención de enchufes", "6.7.6 (jardines)", "jardin"),
                       C("DTMANT", 7, "En caso de mantención de luminarias", "Equipos de iluminación", "jardin",
                         texto="En caso de mantención de luminarias por quema de foco, debe ser repuesto en un plazo máximo de 5 días hábiles.")]},
            {"id": "depende", "si": {}, "quien": "depende",
             "corto": "Depende: lo que está dentro de la cocina (enchufes, focos, automáticos) es nuestro; el suministro y el "
                      "empalme del establecimiento son del sostenedor.",
             "hacer": "Ver si hay luz en el resto del establecimiento.",
             "citas": [C("BASES", 217, "Red de electricidad: El prestador será responsable", "4.2.2", "colegio"),
                       C("BASES", 215, "Suministro de electricidad", "4.2.1", "colegio")]},
        ],
    },

    # ------------------------------------------------------------ AGUA
    {
        "id": "agua", "nombre": "agua",
        "claves": r"\b(agua|llave\w*|griferi\w*|flexible\w*|fuga\w* de agua|sin agua|presion|sifon\w*|monomando)\b",
        "preguntas": [
            {"id": "alcance",
             "texto": "¿Es una fuga o falla dentro de la cocina (llave, flexible, sifón, cañería a la vista) o falta agua en todo "
                      "el establecimiento / es la matriz?",
             "opciones": {
                 "general": ("falta agua en todo el establecimiento, matriz o medidor",
                             r"\b(todo el (colegio|jardin|establecimiento)|matriz|medidor|aguas andinas|corte de agua|sin agua|"
                             r"general|sector|calle)\b"),
                 "interior": ("fuga o falla dentro de la cocina: llave, flexible, sifón, cañería a la vista",
                              r"\b(llave\w*|flexible\w*|sifon\w*|caneria\w*|griferi\w*|lavaplatos|lavafondos|fitting|gotea\w*|"
                              r"en la cocina|de la cocina|bano de (las )?manipuladoras|monomando)\b"),
                 "nose": NOSE}},
        ],
        "conclusiones": [
            {"id": "general", "si": {"alcance": "general"}, "quien": "el sostenedor",
             "corto": "Si falta agua en todo el establecimiento o es la matriz, le toca al sostenedor: el suministro y las "
                      "conexiones hasta la cocina son suyos.",
             "hacer": "Avisar al director; si no se puede cocinar, activar contingencia.",
             "citas": [C("BASES", 215, "Suministro de agua", "4.2.1 Servicios básicos del sostenedor", "colegio"),
                       C("BASES", 278, "Las instituciones son responsables de las respectivas conexiones", "6.7.5.1 (jardines)", "jardin")]},
            {"id": "interior", "si": {"alcance": "interior"}, "quien": "SOSER",
             "corto": "Eso es nuestro: llaves, flexibles, sifones, fitting y cañerías a la vista dentro de la cocina los reparamos nosotros.",
             "nota": "En jardín: grifería en máximo 5 días hábiles.",
             "hacer": "Mandar técnico; si gotea mucho, cerrar la llave de paso.",
             "citas": [C("BASES", 217, "El prestador será responsable de reparar todas las filtraciones", "4.2.2 Red de agua", "colegio"),
                       C("BASES", 281, "El Prestador es responsable de las conexiones de los artefactos", "6.7.6 (jardines)", "jardin"),
                       C("DTMANT", 5, "Frente a problemas de mantención de grifería", "Lavaplatos y grifería", "jardin",
                         texto="Frente a problemas de mantención de grifería el plazo máximo de mantención serán 5 días hábiles.")]},
            {"id": "depende", "si": {}, "quien": "depende",
             "corto": "Depende: lo que está dentro de la cocina (llaves, flexibles, sifones) es nuestro; el suministro y la matriz son del sostenedor.",
             "hacer": "Ver si hay agua en el resto del establecimiento.",
             "citas": [C("BASES", 217, "El prestador será responsable de reparar todas las filtraciones", "4.2.2", "colegio"),
                       C("BASES", 215, "Suministro de agua", "4.2.1", "colegio")]},
        ],
    },

    # ------------------------------------------------------------ DESAGÜE
    {
        "id": "desague", "nombre": "desagüe",
        "claves": r"\b(desague\w*|tapad[oa]s?|tapon\w*|alcantarill\w*|desgrasadora\w*|camara\w*|aguas servidas|rebalsa\w*|"
                  r"no traga|olor a alcantarilla)\b",
        "preguntas": [
            {"id": "alcance",
             "texto": "¿Lo tapado es el desagüe de la cocina (lavaplatos, cámara desgrasadora, ducto que es solo de la cocina) "
                      "o es el alcantarillado que comparte con el resto del establecimiento?",
             "opciones": {
                 "compartido": ("alcantarillado compartido con el resto del establecimiento (baños de alumnos, colector general)",
                                r"\b(compart\w*|todo el (colegio|jardin)|banos de (los )?(alumnos|ninos)|general|colector|matriz|"
                                r"calle|otros banos|del colegio)\b"),
                 "exclusivo": ("desagüe que es solo de la cocina: lavaplatos, cámara desgrasadora, patio de servicio",
                               r"\b(lavaplatos|lavafondos|de la cocina|solo (de )?la cocina|desgrasadora|sifon|rejilla|"
                               r"patio de servicio|bano de (las )?manipuladoras|nuestro)\b"),
                 "nose": NOSE}},
        ],
        "conclusiones": [
            {"id": "exclusivo", "si": {"alcance": "exclusivo"}, "quien": "SOSER",
             "corto": "Si es el desagüe que usa solo la cocina, es nuestro: mantener, destapar y limpiar los ductos de uso exclusivo "
                      "del servicio (y la desgrasadora) nos toca a nosotros.",
             "nota": "En jardín: somos responsables hasta la primera cámara desgrasadora; si la Dirección Regional pide limpiarla, son 3 días hábiles.",
             "hacer": "Destapar y revisar si el origen es grasa o residuos de la cocina.",
             "citas": [C("BASES", 218, "Disposición de aguas servidas", "4.2.2 Aguas servidas", "colegio"),
                       C("BASES", 281, "La evacuación de las aguas servidas es de responsabilidad del Prestador", "6.7.6 (jardines)", "jardin"),
                       C("BASES", 281, "Ante la solicitud de la Dirección Regional de la limpieza", "6.7.6 (jardines)", "jardin")]},
            {"id": "compartido", "si": {"alcance": "compartido"}, "quien": "el sostenedor",
             "corto": "Si es el alcantarillado que comparte con el resto del establecimiento, le toca al sostenedor. "
                      "Ojo: si se comprueba que lo tapó la grasa o los residuos de la cocina, la solución pasa a ser nuestra.",
             "hacer": "Avisar al director; revisar que la cocina no esté botando grasa o sólidos.",
             "citas": [C("BASES", 215, "Instalación de alcantarillado", "4.2.1 Servicios básicos del sostenedor", "colegio"),
                       C("BASES", 281, "En el evento que exista un problema de obstrucción", "6.7.6 (jardines)", "jardin")]},
            {"id": "depende", "si": {}, "quien": "depende",
             "corto": "Depende de si el ducto es solo de la cocina (nuestro) o compartido con el establecimiento (del sostenedor, "
                      "salvo que lo haya tapado la cocina).",
             "hacer": "Ver hasta dónde llega lo tapado.",
             "citas": [C("BASES", 218, "Disposición de aguas servidas", "4.2.2", "colegio"),
                       C("BASES", 215, "Instalación de alcantarillado", "4.2.1", "colegio")]},
        ],
    },

    # ------------------------------------------------------------ GAS
    {
        "id": "gas", "nombre": "gas",
        "claves": r"\b(gas|cilindro\w*|balon\w*|bombona\w*|caseta\w*|estanque\w*|regulador\w*|hermeticidad|sello verde)\b",
        "preguntas": [
            {"id": "parte",
             "texto": "¿Es algo de los cilindros o la caseta (cilindros de hasta 45 kg, regulador, conexión a la cocina o calefón), "
                      "o es la red de cañería o el estanque del establecimiento?",
             "opciones": {
                 "red": ("red de cañería del establecimiento, gas natural o estanque a granel",
                         r"\b(red|caneria\w*|estanque\w*|gas natural|metrogas|granel|matriz|medidor)\b"),
                 "cilindro": ("cilindros, caseta, regulador o conexión de los artefactos de la cocina",
                              r"\b(cilindro\w*|balon\w*|45|caseta\w*|regulador\w*|bombona\w*|conexion\w*|flexible\w*|"
                              r"cocina|fogon\w*|calefon|quemador\w*|piloto|horno)\b"),
                 "nose": NOSE}},
        ],
        "conclusiones": [
            {"id": "red", "si": {"parte": "red"}, "quien": "el sostenedor (instalar y certificar la red)",
             "corto": "La red de cañería o el estanque los instala y certifica el sostenedor. A nosotros nos tocan las conexiones "
                      "dentro de la cocina y que todo lo nuestro sea hermético.",
             "hacer": "Si hay olor a gas: cortar la llave, ventilar y no encender nada. Avisar al director y mandar instalador SEC.",
             "citas": [C("BASES", 218, "La instalación y certificación de la red de suministro", "4.2.2 Red de combustibles", "colegio"),
                       C("BASES", 218, "Red de combustibles: El prestador será responsable", "4.2.2 Red de combustibles", "colegio"),
                       C("BASES", 278, "Las instituciones son responsables de las respectivas conexiones", "6.7.5.1 (jardines)", "jardin")]},
            {"id": "cilindro", "si": {"parte": "cilindro"}, "quien": "SOSER",
             "corto": "Eso es nuestro: la carga e instalación de los cilindros de uso exclusivo, la caseta y las conexiones de la "
                      "cocina las vemos nosotros, siempre con instalador SEC.",
             "nota": "En jardín: prueba de hermeticidad semestral y después de cada intervención.",
             "hacer": "Si hay olor a gas: cortar, ventilar, no encender nada y mandar instalador SEC.",
             "citas": [C("BASES", 218, "Con respecto a la debida carga y recarga", "4.2.2 Red de combustibles", "colegio"),
                       C("BASES", 281, "La mantención y/o reparación de las casetas de gas", "6.7.6 (jardines)", "jardin"),
                       C("DTMANT", 2, "Se deberán efectuar pruebas de hermeticidad", "Casetas de gas, cilindros y bombonas", "jardin",
                         texto="Se deberán efectuar pruebas de hermeticidad de las conexiones de gas de manera semestral o "
                               "posterior a cada instalación, reparación o reinstalación de algún equipo.")]},
            {"id": "depende", "si": {}, "quien": "depende",
             "corto": "Depende: cilindros, caseta y conexiones de la cocina son nuestros; la red de cañería o el estanque del establecimiento son del sostenedor.",
             "hacer": "Si hay olor a gas: cortar, ventilar y no encender nada.",
             "citas": [C("BASES", 218, "La instalación y certificación de la red de suministro", "4.2.2", "colegio")]},
        ],
    },

    # ------------------------------------------------------------ PLAGAS
    {
        "id": "plagas", "nombre": "plagas",
        "claves": r"\b(plaga\w*|raton\w*|ratas?|roedor\w*|cucaracha\w*|palom\w*|murcielag\w*|gatos?|perros?|moscas?|"
                  r"hormiga\w*|termita\w*|guarén\w*|guaren\w*|fecas?)\b",
        "preguntas": [
            {"id": "donde",
             "texto": "¿Las vieron dentro de la cocina o la bodega, o vienen de afuera (patio, entretecho, otras partes del establecimiento)?",
             "opciones": {
                 "fuera": ("vienen de afuera: patio, entretecho, salas, alrededores",
                           r"\b(afuera|patio|entretecho|techo|alrededor\w*|salas?|vecino\w*|exterior|comedor|todo el|del colegio)\b"),
                 "dentro": ("dentro de la cocina, bodega o despensa",
                            r"\b(cocina|bodega|despensa|dentro|adentro|en los alimentos|en la mercaderia|estante\w*)\b"),
                 "nose": NOSE}},
        ],
        "conclusiones": [
            {"id": "dentro", "si": {"donde": "dentro"}, "quien": "SOSER (y avisar)",
             "corto": "Dentro de la cocina o bodega nos toca a nosotros: control con empresa autorizada, avisar a la Dirección "
                      "Regional, coordinar con el sostenedor, y después higienizar y botar lo contaminado.",
             "hacer": "Llamar a la empresa de control de plagas, avisar a la Dirección Regional y proteger los alimentos.",
             "citas": [C("BASES", 219, "Plagas: el prestador debe mantener las áreas", "4.2.2 Requisitos sanitarios", "colegio"),
                       C("BASES", 219, "Ante la presencia de plagas que afecten la inocuidad", "4.2.2 Plagas", "colegio")]},
            {"id": "fuera", "si": {"donde": "fuera"}, "quien": "el sostenedor",
             "corto": "Si vienen de afuera, le toca al sostenedor: él responde por las plagas y los animales en todo el "
                      "establecimiento y las zonas que dan a la cocina. Nosotros coordinamos y cuidamos que no entren.",
             "hacer": "Avisar por escrito al director y revisar que puertas, mallas y ventanas sellen.",
             "citas": [C("BASES", 216, "Plagas: el sostenedor es responsable", "4.2.1 Infraestructura del sostenedor", "colegio"),
                       C("BASES", 216, "Adicionalmente, el sostenedor debe evitar la presencia", "4.2.1", "colegio"),
                       SGC_HERMETICIDAD]},
            {"id": "depende", "si": {}, "quien": "los dos, coordinados",
             "corto": "En plagas se trabaja coordinado: dentro de la cocina y bodega nos toca a nosotros; en el resto del "
                      "establecimiento y lo que da a la cocina, al sostenedor.",
             "hacer": "Ver por dónde están entrando.",
             "citas": [C("BASES", 219, "Plagas: el prestador debe mantener las áreas", "4.2.2", "colegio"),
                       C("BASES", 216, "Plagas: el sostenedor es responsable", "4.2.1", "colegio")]},
        ],
    },
]

# ------------------------------------------------------------ FICHA GENERAL (cuando no calza ninguna)
GENERAL = {
    "id": "general", "nombre": "el problema",
    "claves": r"$^",
    "preguntas": [
        {"id": "que",
         "texto": "Cuéntame un poco más: ¿es un equipo o artefacto de la cocina (refri, horno, campana, calefón), una instalación "
                  "de adentro (enchufe, llave, cañería a la vista), algo del edificio (muro, techo, losa, grieta) o algo fuera de la cocina?",
         "opciones": {
             "fuera": ("algo fuera de la cocina, bodega y baño de manipuladoras",
                       r"\b(fuera|afuera|sala\w*|pasillo\w*|gimnasio|oficina\w*|porteria|otra parte|del colegio)\b"),
             "estructura": ("algo del edificio: muro, techo, losa, grieta, estructura",
                            r"\b(muro\w*|pared\w*|techo|losa|loza|grieta\w*|estructur\w*|piso\w*|viga\w*|pilar\w*|edificio)\b"),
             "equipo": ("un equipo, mueble o artefacto de la cocina (refrigerador, horno, cocina, campana, calefón, mesón, estante)",
                        r"\b(equipo\w*|refri\w*|refrigerador\w*|congelador\w*|horno\w*|cocina|fogon\w*|campana|calefon|termo|"
                        r"meson\w*|estante\w*|estanteria\w*|lavaplatos|marmita\w*|batidora|balanza|mueble\w*|carro\w*|artefacto\w*)\b"),
             "instalacion": ("una instalación de adentro: enchufe, llave, cañería a la vista, cable",
                             r"\b(enchufe\w*|llave\w*|caneria\w*|cable\w*|interruptor\w*|conexion\w*|instalacion\w*)\b"),
             "nose": NOSE}},
        {"id": "causa", "cuando": {"que": "estructura"},
         "texto": "¿Y sabes si lo causó alguien de nosotros (manipuladoras, técnicos, un trabajo nuestro)?",
         "opciones": {
             "soser": ("sí, lo causó personal o un trabajo de SOSER",
                       r"\b(si|fuimos|fue (la|el|un) (manipuladora|tecnico|maestro)|nosotr\w*|nuestr\w*|manipulador\w*|soser)\b"),
             "no": ("no, no fue SOSER (desgaste, tiempo, terceros)",
                    r"\b(no|nunca|tiempo|viej\w*|solo|sola|alumn\w*|robo|desgast\w*)\b"),
             "nose": NOSE}},
    ],
    "conclusiones": [
        {"id": "fuera", "si": {"que": "fuera"}, **{k: v for k, v in FUERA_DEL_SERVICIO.items() if k not in ("id", "si")}},
        {"id": "estructura_soser", "si": {"que": "estructura", "causa": "soser"}, "quien": "SOSER",
         "corto": "Si lo causamos nosotros, aunque sea estructura, nos toca repararlo al tiro y a nuestro costo.",
         "hacer": "Reparar y dejar registro.",
         "citas": CAUSADO_SOSER},
        {"id": "estructura", "si": {"que": "estructura"}, "quien": "el sostenedor",
         "corto": "Si es estructura (muro, techo, losa, grietas) y no lo causamos nosotros, le toca al sostenedor.",
         "hacer": "Informar por escrito al director con fotos y registrarlo en la matriz de riesgo.",
         "citas": ESTRUCTURAL_SOSTENEDOR},
        {"id": "equipo", "si": {"que": "equipo"}, "quien": "SOSER",
         "corto": "Los equipos, muebles y artefactos de la cocina son nuestros: tenemos que tenerlos, reponerlos y mantenerlos "
                  "según el Anexo 17 (y también mantener los que son del establecimiento).",
         "hacer": "Revisar si está en el Anexo 17 y mandar técnico.",
         "citas": [C("BASES", 221, "El prestador será responsable de proveer y/o reponer", "4.3 Mobiliario, equipamiento y artefactos"),
                   C("BASES", 221, "Lo anterior, sin perjuicio de la responsabilidad del prestador de realizar mantención", "4.3.1")]},
        {"id": "instalacion", "si": {"que": "instalacion"}, "quien": "SOSER",
         "corto": "Las instalaciones de adentro de la cocina (enchufes, llaves, cañerías a la vista, conexiones) son nuestras.",
         "nota": "En jardín ojo: somos responsables de las conexiones de los artefactos, pero no podemos modificar las "
                 "instalaciones eléctricas, de gas o sanitarias del establecimiento.",
         "hacer": "Mandar técnico (SEC si es luz o gas).",
         "citas": [C("BASES", 217, "Servicios básicos: Reparar, limpiar y mantener", "4.2.2 Servicios básicos", "colegio"),
                   C("BASES", 281, "El Prestador no podrá realizar modificaciones", "6.7.6 (jardines)", "jardin")]},
        {"id": "depende", "si": {}, "quien": "depende",
         "corto": "Con lo que sé todavía no puedo decirte. La regla general es: si lo causamos nosotros, nos toca; si es "
                  "estructura o redes que llegan a la cocina, es del sostenedor; y lo que está dentro de la cocina y sirve para operar, "
                  "lo mantenemos nosotros.",
         "hacer": "Mándame una foto o cuéntame qué es exactamente.",
         "citas": CAUSADO_SOSER + ESTRUCTURAL_SOSTENEDOR + MANTENER_OPERATIVO},
    ],
}
