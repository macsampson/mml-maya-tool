# MML Maya Tools


> **Note**: This project is currently a **Work in Progress**.

![MML Maya Tool Screenshot](images/megaman.gif)

A Python-based asset tool for importing **Mega Man Legends (PS1)** assets into Maya. This is mainly a legacy systems research project thats built upon the awesome work of @kion-dgl (The GOAT of MML reverse engineering).

## Key Features

- **Custom Binary Parsing**:
  - Implements a parser for the proprietary `.ebd` (Entity/Model) and `.tim` (Texture) PS1 formats.
  - Handles legacy fixed-point arithmetic (12-bit packed coordinates) and PS1 specific coordinate spaces.

- **Maya Integration**:
  - **Direct Import**: Reconstructs models, skeletons, and materials directly in Maya using `maya.api.OpenMaya` and `maya.cmds`.
  - **Rigid Binding**: Automatically sets up rigging to replicate the original game's look and feel with the action figure style (100% weight per limb).
  - **Animation Support**: Parses and applies original frame-based animations to the generated skeleton.

- **Custom ASCII FBX 7.4 exporter**:
  - Generates valid FBX files with skeletal hierarchies and animation data without relying on the official Autodesk FBX SDK.
  - **Portability**: Runs standalone without needing a Maya license or heavy SDK installation.

- **Texture Management**:
  - Includes a database system to map models to their correct texture pages and palettes (Color Look-Up Tables).
  - Handles UV space conversion and texture compositing.


## Future Plans

- [ ] add support for USD export
- [ ] allow users to select which face textures to apply to the model
- [ ] possibly split this toolset into multiple tools

## Usage

This tool is intended strictly for **research and preservation purposes only**.

It serves as a technical study of legacy game engine architecture and asset pipelines. Please respect the original copyright holders; this tool should not be used to infringe on intellectual property rights.
