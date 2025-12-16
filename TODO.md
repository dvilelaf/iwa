Este proyecto, llamado iwa, consiste en un framework para gestionar carteras crypto e interactuar con smart contracts y protocolos crypto de una forma segura.

La base central es una clase que permite generar claves privadas y almacenarlas de forma encriptada y excepcionalmente segura.

Varios protocolos crypto pueden ser integrados facilmente como plugins. Los plugins son leidos dinamicamente desde la carpeta plugins. Pueden definir su propia configuracion y sus modelos de pydantic, y son cargados dinamicamente en tiempo de ejecucion. Los plugins de estos protocolos deberian seguir un formato estandarizado. Puedes ver varios protocolos en src/iwa/protocols (olas - aka autonolas) y Gnosis (que a su vez integra Cow Swap y Safe, siendo Safe parte del core, ya que es crucial poder gestions carteras multisig). Estas integraciones no están terminadas aún.

Revisa la base de código, analiza su seguridad y estructura. Tienes vía libre para reestructurar el proyecto como mejor consideres, teniendo en cuenta que el objetivo es que sea seguro, funcional y muy modular/extendible.

Idealmente, las claves criptográficas jamás deberían de salir del key storage. El flujo ideal es:
- Un clase derivada de Contract devuelve una transaccion
- La clase KeyStorage se encarga de firmar la transaccion
- La clase Wallet se encarga de enviar la transaccion

Entiendo uqe hay alguna libreria externa, como la de Cowswap, que exige que se le pase la clave privada. En tal caso, podemos hacer una excepción, pero evitalo donde sea posible.

Sigue las mejores prácticas de seguridad y diseño, y manten una buena separation of concerns.

Las tareas son:
- Analiza la base de código. Tanto su estructura como su seguridad
- Reestructura el proyecto como consideres necesario
- Soluciona los problemas de seguridad que encuentres
- Implementa los protocolos que faltan
- Crea unit tests
- Arregla el CLI para que tambiñen sea extensible. Cada plugin debe poder definir sus propios comandos.
- Añade soporte para Telegram (debe ser un plugin). El usuario debe poder enviar comandos via telegram.
- Prepara el proyecto para que pueda ser empaquetado y subido a Pypi.
- Usa uv para la gestion de paquetes
- Convierte el Makefile a un Justfile
- El proyecto debe poder correr dentro de un Docker tambien, añade un docker compose y targets just para correrlo y subirlo a docker hub.


A tener en cuenta:
- Implementa un sistema central de firma, envio y verificacion de transacciones. Idealmente, se deben de poder gestionar varias transacciones en multiples blockchains de forma simultanea.
- Este sistema debe soportar mútiples cadenas (Gnosis, Base, Ethereum), con detección de RPCs no funcionales y autorotación de los mismos
- Gestión automática del gas cuando una trasnacción falla.

Encontrarás gran parte de estas funcionalidades parcialmente implementadas en el proyecto, pero puedes modificarlas.